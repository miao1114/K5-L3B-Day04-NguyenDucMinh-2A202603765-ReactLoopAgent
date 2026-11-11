"""Tests offline cho phần bonus của agent: giới hạn retry 429, phân trang và context nhiễu."""
import json
import sys
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'bonus'))
from agent import run_agent, MAX_RATE_LIMITED
from bonus.tools import BonusTools
from test_agent import ScriptedProvider, call, final


def tool_events(result, name):
    return [x for x in result['trace'] if x['event'] == 'tool' and x['name'] == name]


class RetryLimitTests(unittest.TestCase):
    def test_persistent_429_is_blocked_after_limit(self):
        t = BonusTools(scenario='rate_limit_always')
        p = ScriptedProvider([call(str(i), 'get_vercel_status', {}) for i in range(5)]
                             + [final('Không biết trạng thái Vercel do 429.')])
        result = run_agent('Kiểm tra Vercel', p, t, max_steps=8)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), MAX_RATE_LIMITED)
        self.assertEqual(sum(x['event'] == 'retry_blocked' for x in result['trace']), 2)
        self.assertEqual(t.calls[('get_vercel_status', 'vercel')], MAX_RATE_LIMITED)
        self.assertEqual(json.loads(p.histories[3][-1]['content'])['attempts_left'], 0)
        self.assertEqual(json.loads(p.histories[4][-1]['content'])['error'], 'RETRY_LIMIT_REACHED')

    def test_rate_limit_is_counted_per_provider(self):
        t = BonusTools(scenario='rate_limit_always')
        p = ScriptedProvider([call(str(i), 'get_vercel_status', {}) for i in range(3)]
                             + [call('g', 'get_github_status', {}), final()])
        result = run_agent('x', p, t, max_steps=8)
        self.assertEqual(json.loads(p.histories[4][-1]['content'])['provider'], 'github')
        self.assertEqual(result['status'], 'completed')

    def test_unretried_429_gets_one_nudge(self):
        t = BonusTools(scenario='rate_limit_once')
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), final('Vercel bị 429.'),
                              call('b', 'get_vercel_status', {}), final('Vercel none sau khi thử lại.')])
        result = run_agent('x', p, t, max_steps=6)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(len(tool_events(result, 'get_vercel_status')), 2)
        gate = [x for x in result['trace'] if x['event'] == 'validation_unretried_rate_limit']
        self.assertEqual(gate[0]['tools'], {'get_vercel_status': 1})
        self.assertIn('RATE_LIMITED', p.histories[2][-1]['content'])

    def test_no_retry_nudge_without_budget(self):
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), final('Vercel bị 429.')])
        result = run_agent('x', p, BonusTools(scenario='rate_limit_once'), max_steps=3)
        self.assertEqual(result['status'], 'completed')
        self.assertFalse(any(x['event'] == 'validation_unretried_rate_limit' for x in result['trace']))

    def test_retry_after_is_respected_within_budget(self):
        class SlowLimit(BonusTools):
            def execute(self, name, args):
                return {'ok': False, 'error': 'RATE_LIMITED', 'http_status': 429, 'retry_after': '120'}
        p = ScriptedProvider([call('a', 'get_npm_status', {}), call('b', 'get_npm_status', {}), final()])
        result = run_agent('x', p, SlowLimit(), max_steps=5)
        self.assertEqual(json.loads(p.histories[2][-1]['content'])['error'], 'RETRY_AFTER_TOO_LONG')
        self.assertEqual(len(tool_events(result, 'get_npm_status')), 1)


class ContextTests(unittest.TestCase):
    def test_pagination_note_when_timeline_has_more_pages(self):
        p = ScriptedProvider([call('a', 'get_incident_details', {'provider': 'vercel', 'incident_id': 'sps6n39gm4sg'}),
                              final('https://www.vercel-status.com/incidents/sps6n39gm4sg')])
        result = run_agent('x', p, BonusTools(), max_steps=4)
        self.assertEqual(result['status'], 'completed')
        seen = json.loads(p.histories[1][-1]['content'])
        self.assertIn('offset=2', seen['pagination_note'])

    def test_noise_is_compacted_before_reaching_model(self):
        p = ScriptedProvider([call('a', 'get_vercel_status', {}), final()])
        result = run_agent('x', p, BonusTools(scenario='noisy'), max_steps=3)
        seen = json.loads(p.histories[1][-1]['content'])
        self.assertLess(len(seen['distractors']), 10)
        self.assertEqual(tool_events(result, 'get_vercel_status')[0]['compacted'], {'distractors': 160})
        self.assertEqual(seen['provider'], 'vercel')


if __name__ == '__main__':
    unittest.main()
