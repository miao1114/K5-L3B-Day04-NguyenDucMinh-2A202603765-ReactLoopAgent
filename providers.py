"""Bốn provider cùng một interface. Không chứa agent loop."""
import json
import os
import time
import urllib.error
import urllib.request
import uuid

CONFIG = {
    'openai': ('OPENAI_API_KEY', 'https://api.openai.com/v1/chat/completions'),
    'gemini': ('GEMINI_API_KEY', 'https://generativelanguage.googleapis.com/v1beta/openai/chat/completions'),
    'openrouter': ('OPENROUTER_API_KEY', 'https://openrouter.ai/api/v1/chat/completions'),
    'opencode': ('OPENCODE_GO_API_KEY', 'https://opencode.ai/inference/go/openai/v1/chat/completions'),
    'anthropic': ('ANTHROPIC_API_KEY', 'https://api.anthropic.com/v1/messages'),
}


MAX_RETRIES = 3
MAX_WAIT_SECONDS = 60


def _retry_wait(exc, attempt):
    """Số giây nên chờ trước khi thử lại, hoặc None nếu không nên retry."""
    if exc.code not in (429, 500, 503) or attempt >= MAX_RETRIES:
        return None
    body = exc.read().decode('utf-8', errors='replace')
    if 'per day' in body.lower() or 'PerDay' in body:
        return None  # Hết quota theo ngày: chờ trong vài phút cũng vô ích.
    retry_after = exc.headers.get('Retry-After') if exc.headers else None
    try:
        wait = float(retry_after) if retry_after else 5 * 2 ** attempt
    except ValueError:
        wait = 5 * 2 ** attempt
    return wait if wait <= MAX_WAIT_SECONDS else None


def post_json(url, headers, payload):
    data = json.dumps(payload).encode()
    for attempt in range(MAX_RETRIES + 1):
        req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', **headers})
        try:
            with urllib.request.urlopen(req, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            wait = _retry_wait(exc, attempt)
            if wait is not None:
                time.sleep(wait)
                continue
            # Do not print response bodies: they may contain account or request data.
            hint = ' (rate limit/hết quota)' if exc.code == 429 else ''
            raise RuntimeError(f'Provider trả HTTP {exc.code}{hint}; kiểm tra model, key và quota.') from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f'Không kết nối được provider: {exc.reason}') from exc


class Provider:
    """complete(messages, schemas) -> {message, calls, finish, usage}.

    messages: system/user/assistant/tool theo format Chat Completions. message trả về
    cần được append nguyên vẹn; tool result có role, tool_call_id, content (JSON string).
    """
    def __init__(self, name, model):
        if name not in CONFIG:
            raise ValueError(f'Provider không hợp lệ: {name}')
        if not model:
            raise ValueError('Cần đặt MODEL là model có hỗ trợ tool calling.')
        self.name, self.model = name, model
        key_name, self.url = CONFIG[name]
        self.key = os.getenv(key_name)
        if not self.key:
            raise ValueError(f'Thiếu {key_name}; xem README.md.')
        self.session_id = str(uuid.uuid4())  # Mỗi Provider (mỗi case) là một conversation.

    def complete(self, messages, schemas):
        if self.name == 'anthropic':
            return self._anthropic(messages, schemas)
        payload = {'model': self.model, 'messages': messages}
        if schemas:
            payload['tools'] = schemas
        headers = {'Authorization': f'Bearer {self.key}'}
        if self.name == 'opencode':
            # OpenCode Go cần User-Agent riêng và cùng session ID cho một conversation.
            headers.update({'User-Agent': 'StatusAgentLab/1.0', 'x-opencode-session': self.session_id})
        data = post_json(self.url, headers, payload)
        choice = data['choices'][0]
        message = choice['message']
        calls = [{'id': c['id'], 'name': c['function']['name'], 'arguments': c['function']['arguments']} for c in message.get('tool_calls') or []]
        return {'message': message, 'calls': calls, 'finish': choice.get('finish_reason'), 'usage': data.get('usage', {})}

    def _anthropic(self, messages, schemas):
        system = '\n'.join(m['content'] for m in messages if m['role'] == 'system')
        native = []
        for m in messages:
            if m['role'] == 'system':
                continue
            if m['role'] == 'assistant':
                blocks = []
                if m.get('content'):
                    blocks.append({'type': 'text', 'text': m['content']})
                for call in m.get('tool_calls', []):
                    blocks.append({'type': 'tool_use', 'id': call['id'], 'name': call['function']['name'], 'input': json.loads(call['function']['arguments'])})
                native.append({'role': 'assistant', 'content': blocks})
            elif m['role'] == 'tool':
                block = {'type': 'tool_result', 'tool_use_id': m['tool_call_id'], 'content': m['content']}
                if native and native[-1]['role'] == 'user' and isinstance(native[-1]['content'], list):
                    native[-1]['content'].append(block)
                else:
                    native.append({'role': 'user', 'content': [block]})
            else:
                native.append({'role': 'user', 'content': m['content']})
        tools = [{'name': x['function']['name'], 'description': x['function']['description'], 'input_schema': x['function']['parameters']} for x in schemas]
        payload = {'model': self.model, 'max_tokens': 1024, 'system': system, 'messages': native}
        if tools:
            payload['tools'] = tools
        data = post_json(self.url, {'x-api-key': self.key, 'anthropic-version': '2023-06-01'}, payload)
        blocks = data['content']
        calls = [{'id': b['id'], 'name': b['name'], 'arguments': json.dumps(b['input'], ensure_ascii=False)} for b in blocks if b['type'] == 'tool_use']
        text = '\n'.join(b['text'] for b in blocks if b['type'] == 'text')
        message = {'role': 'assistant', 'content': text or None}
        if calls:
            message['tool_calls'] = [{'id': c['id'], 'type': 'function', 'function': {'name': c['name'], 'arguments': c['arguments']}} for c in calls]
        reason = {'end_turn': 'stop', 'tool_use': 'tool_calls', 'max_tokens': 'length'}.get(data.get('stop_reason'), data.get('stop_reason'))
        return {'message': message, 'calls': calls, 'finish': reason, 'usage': data.get('usage', {})}
