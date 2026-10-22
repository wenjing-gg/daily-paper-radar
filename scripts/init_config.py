"""生成首次使用的两个本地配置文件；已有文件保留不覆盖。"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    for source, target in [('config/_template.json', 'config/profile.json'), ('.env.example', '.env')]:
        destination = ROOT / target
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            with destination.open('x', encoding='utf-8') as handle:
                handle.write((ROOT / source).read_text(encoding='utf-8'))
            if target == '.env':
                destination.chmod(0o600)
            print(f'已创建：{target}')
        except FileExistsError:
            print(f'已有文件，保留不覆盖：{target}')
    print('下一步：在 config/profile.json 填关键词即可，关注方向和论文偏好可留空；在 .env 填模型与飞书配置。')


if __name__ == '__main__':
    main()
