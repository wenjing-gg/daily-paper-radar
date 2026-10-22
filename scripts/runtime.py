"""共享路径、原子写入、脱敏和跨平台运行锁。"""
from __future__ import annotations
import json
import os
import re
from contextlib import contextmanager
from pathlib import Path
from datetime import datetime, timedelta, timezone

def beijing_today():
    """展示与日报分批统一使用北京时间，独立于宿主机时区。"""
    return datetime.now(timezone(timedelta(hours=8))).date()


ROOT = Path(__file__).resolve().parent.parent
def load_env(path=None):
    """读取本地 .env，系统环境变量优先；不执行命令、不展开变量。"""
    path = Path(path or ROOT / '.env')
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding='utf-8-sig').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        name, sep, value = line.partition('=')
        name, value = name.strip(), value.strip()
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', name):
            raise ValueError(f'.env 第 {number} 行格式错误（内容已隐藏）')
        if value.startswith(('"', "'")):
            quote = value[0]
            end = value.find(quote, 1)
            if end < 0 or (value[end + 1:].strip() and not value[end + 1:].lstrip().startswith('#')):
                raise ValueError(f'.env 第 {number} 行引号格式错误（内容已隐藏）')
            value = value[1:end]
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].rstrip()
        os.environ.setdefault(name, value)


load_env()
PROFILE = Path(os.environ.get('DAILY_PAPER_RADAR_PROFILE', ROOT / 'config/profile.json')).resolve()
STATE = Path(os.environ.get('DAILY_PAPER_RADAR_STATE', ROOT / 'state')).resolve()


def write_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


def redact(text):
    text = str(text)
    for name, value in os.environ.items():
        if len(value) >= 4 and any(s in name.upper() for s in ('SECRET', 'TOKEN', 'KEY', 'WEBHOOK', 'PASSWORD')):
            text = text.replace(value, '[已脱敏]')
    return re.sub(r'https?://[^\s\"\'<>]+/hook/[^\s\"\'<>]+', '[飞书地址已脱敏]', text)


@contextmanager
def run_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a+b') as handle:
        # Windows 禁止读取其他进程锁住的字节；用文件元数据判断是否需初始化。
        if os.fstat(handle.fileno()).st_size == 0:
            handle.write(b'0')
            handle.flush()
        handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('已有任务正在运行') from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == 'nt':
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)
