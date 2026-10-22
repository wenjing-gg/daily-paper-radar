"""构建只含公开资源的 ZIP，不打包个人配置、凭据、状态和日志。"""
from pathlib import Path
import zipfile
import re
import hashlib

ROOT = Path(__file__).resolve().parent.parent


def release_files():
    files = [ROOT / name for name in ('SKILL.md', 'README.md', 'README.zh-CN.md', 'VERSION', 'requirements.txt', 'CHANGELOG.md', 'CONTRIBUTING.md', 'SECURITY.md', 'CODE_OF_CONDUCT.md', 'LICENSE', '.env.example', '.gitignore', 'config/_template.json', 'config/qs_top100.json', 'config/trusted_teams.json')]
    for directory, extensions in [('scripts', {'.py', '.sh', '.ps1'}), ('tests', {'.py'}), ('docs', {'.md'}), ('examples', {'.md', '.json'}), ('.github', {'.yml', '.md'})]:
        files.extend(p for p in (ROOT / directory).rglob('*') if p.is_file() and p.suffix in extensions and '__pycache__' not in p.parts)
    # 展示资源采用明确清单，避免打包无关素材。
    for name in ('assets/banner.png', 'assets/logo.png',
                 'assets/screenshots/feishu-digest-zh.png', 'assets/screenshots/feishu-digest-en.png',
                 'assets/screenshots/feishu-paper-detail-zh.png', 'assets/screenshots/feishu-archive-zh.png'):
        if (ROOT / name).is_file():
            files.append(ROOT / name)
    return sorted(files)


def main():
    version = (ROOT / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?', version):
        raise ValueError('VERSION 必须是有效版本号，如 0.1.0 或 0.2.0-rc.1')
    target = ROOT / f'dist/daily-paper-radar-{version}.zip'
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
        for path in release_files():
            archive.write(path, Path('daily-paper-radar') / path.relative_to(ROOT))
    checksum = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_suffix('.zip.sha256').write_text(f'{checksum}  {target.name}\n', encoding='utf-8')
    print(f'已生成公开发布包与 SHA-256 校验和：{target}')


if __name__ == '__main__':
    main()
