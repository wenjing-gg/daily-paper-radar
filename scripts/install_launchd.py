#!/usr/bin/env python3
"""生成或安装 macOS 每日任务，不向 plist 写入凭据。"""
import argparse
import os
from pathlib import Path
import plistlib
import subprocess
import sys
from runtime import ROOT


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--time', default='10:30')
    ap.add_argument('--profile', type=Path, default=ROOT / 'config/profile.json')
    ap.add_argument('--state-dir', type=Path, default=ROOT / 'state')
    ap.add_argument('--uninstall', action='store_true')
    ap.add_argument('--output', type=Path, help='只生成 plist，不安装任务')
    args = ap.parse_args()
    hour, minute = map(int, args.time.split(':'))
    if not 0 <= hour < 24 or not 0 <= minute < 60:
        ap.error('时间必须为 HH:MM')
    label = 'com.paperradar.daily'
    legacy_label = 'com.arxiv.radar'
    dest = args.output or Path.home() / 'Library/LaunchAgents' / (label + '.plist')
    legacy_dest = Path.home() / 'Library/LaunchAgents' / (legacy_label + '.plist')
    if not args.output and sys.platform != 'darwin':
        ap.error('安装仅支持 macOS')
    if args.uninstall:
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{label}'], capture_output=True)
        subprocess.run(['launchctl', 'bootout', f'gui/{os.getuid()}/{legacy_label}'], capture_output=True)
        dest.unlink(missing_ok=True)
        if legacy_dest != dest:
            legacy_dest.unlink(missing_ok=True)
        return
    state_dir = args.state_dir.resolve()
    state_dir.mkdir(parents=True, exist_ok=True)
    data = {
        'Label': label,
        'ProgramArguments': [sys.executable, str(ROOT / 'scripts/run_daily.py'),
                             '--profile', str(args.profile.resolve()), '--state-dir', str(args.state_dir.resolve())],
        'WorkingDirectory': str(ROOT),
        'StartCalendarInterval': {'Hour': hour, 'Minute': minute},
        'EnvironmentVariables': {'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'PYTHONUTF8': '1'},
        'ProcessType': 'Background',
        'RunAtLoad': False,
        'StandardOutPath': str(state_dir / 'launchd.out.log'),
        'StandardErrorPath': str(state_dir / 'launchd.err.log'),
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(plistlib.dumps(data))
    if not args.output:
        domain = f'gui/{os.getuid()}'
        subprocess.run(['launchctl', 'bootout', f'{domain}/{label}'], capture_output=True)
        if legacy_dest.exists():
            subprocess.run(['launchctl', 'bootout', f'{domain}/{legacy_label}'], capture_output=True)
            legacy_dest.unlink(missing_ok=True)
            print(f'已移除旧任务 {legacy_label}，避免重复运行。')
        subprocess.run(['launchctl', 'bootstrap', domain, str(dest)], check=True)
    print(f'已生成：{dest}；时间采用本机时区 {args.time}')


if __name__ == '__main__':
    main()
