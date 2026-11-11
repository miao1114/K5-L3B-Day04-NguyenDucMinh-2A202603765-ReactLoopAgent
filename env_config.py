"""Đọc .env đơn giản bằng standard library; không ghi đè môi trường hiện có."""
import os
from pathlib import Path
import shlex


def load_env(path=None):
    path = Path(path) if path is not None else Path(__file__).with_name('.env')
    if not path.is_file():
        return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        name, separator, value = line.partition('=')
        name = name.strip()
        if not separator or not name.isidentifier():
            continue
        parts = shlex.split(value, comments=True)
        os.environ.setdefault(name, ' '.join(parts))
