"""用公开固定样例预览日报和飞书卡片；不联网、不调用模型、不发送消息。"""
import argparse
from datetime import date
import json
from pathlib import Path

from render_digest import render_digest
from sinks.feishu_bot import _build_card

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=['zh', 'en'], default='zh')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'state/demo')
    args = parser.parse_args()
    papers = json.loads((ROOT / f'examples/papers.{args.language}.json').read_text(encoding='utf-8'))['papers']
    en = args.language == 'en'
    title = 'Daily Paper Radar · Layout example' if en else '论文日报 · 排版样例'
    profile = {'digest_language': args.language, 'digest_title': title,
               'render': {'footer': '*Static layout example; not a live model run or delivery record.*' if en else '*固定排版样例，非模型实测或真实推送记录。*'}}
    day = date(2026, 10, 22)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    for mode in ('full', 'concise'):
        body = render_digest(papers, day, profile, mode)
        (args.output_dir / f'digest-{mode}.{args.language}.md').write_text(body + '\n', encoding='utf-8')
        if mode == 'concise':
            (args.output_dir / f'feishu-card.{args.language}.json').write_text(json.dumps(_build_card(title, body, 'blue'), ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'离线样例已生成：{args.output_dir}')


if __name__ == '__main__':
    main()
