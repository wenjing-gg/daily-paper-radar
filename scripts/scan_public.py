"""使用 Gitleaks 标准规则扫描发布清单或实际暂存内容；不打印敏感值。"""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

from build_release import ROOT, release_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged', action='store_true', help='扫描 Git 索引中的实际文件内容，不读取工作区替代版本')
    args = parser.parse_args()
    scanner = shutil.which('gitleaks')
    if not scanner:
        parser.exit(2, '请先安装 Gitleaks；缺少扫描工具不能视为扫描通过。\n')
    with tempfile.TemporaryDirectory(prefix='radar-public-scan-') as folder:
        target = Path(folder)
        if args.staged:
            result = subprocess.run(['git', 'diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'], cwd=ROOT, capture_output=True, check=True)
            names = [os.fsdecode(name) for name in result.stdout.split(b'\0') if name]
            if not names:
                print('暂无暂存文件；没有执行扫描，不代表工作区或历史已通过。')
                return 0
            for name in names:
                path = Path(name)
                if path.is_absolute() or '..' in path.parts:
                    parser.exit(2, '拒绝异常暂存路径。\n')
                dest = target / path
                dest.parent.mkdir(parents=True, exist_ok=True)
                content = subprocess.run(['git', 'show', ':' + name], cwd=ROOT, capture_output=True, check=True).stdout
                dest.write_bytes(content)
        else:
            paths = release_files()
            names = [str(p.relative_to(ROOT)) for p in paths]
            for source in paths:
                if source.is_symlink():
                    parser.exit(2, '发布清单包含符号链接，请先核实目标。\n')
                dest = target / source.relative_to(ROOT)
                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, dest)
        forbidden = [name for name in names if Path(name).name in ('.env', 'AGENTS.md', 'CLAUDE.md')
                     or Path(name).name.startswith('profile.') or Path(name).suffix == '.log'
                     or any(part in ('state', '.history', '.venv') for part in Path(name).parts)]
        if forbidden:
            parser.exit(1, '待发布内容包含私人配置、指令、状态或日志；请移除后复扫。\n')
        env = {k: v for k, v in os.environ.items() if not k.startswith('GITLEAKS_')}
        result = subprocess.run([scanner, 'dir', str(target), '--redact', '--no-banner',
                                 '--ignore-gitleaks-allow', '--gitleaks-ignore-path', str(target / 'no-ignore-file')],
                                cwd=target, env=env)
        if result.returncode == 0:
            print(f'标准敏感信息扫描通过：{len(names)} 个文件；输出已脱敏。')
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
