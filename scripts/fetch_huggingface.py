"""抓取 Hugging Face Daily Papers，保留社区投票和讨论链接。"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from paper_metadata import code_links

ENDPOINT = 'https://huggingface.co/api/daily_papers'


def normalize_entry(entry):
    paper = entry.get('paper')
    if not isinstance(paper, dict):
        raise ValueError('Hugging Face 返回的 paper 结构无效')
    aid = re.sub(r'v\d+$', '', str(paper.get('id', '')))
    if not re.fullmatch(r'\d{4}\.\d{4,5}', aid):
        return None
    return {
        'arxiv_id': aid,
        'title': paper.get('title') or entry.get('title') or '',
        'summary': paper.get('summary') or entry.get('summary') or '',
        'authors': ', '.join(a.get('name', '') for a in paper.get('authors', []) if isinstance(a, dict)),
        'abs_url': f'https://arxiv.org/abs/{aid}',
        'pdf_url': f'https://arxiv.org/pdf/{aid}.pdf',
        'published': paper.get('publishedAt', ''),
        'categories': [],
        'announce_type': 'new',
        'sources': ['huggingface'],
        'hf_upvotes': max(0, int(paper.get('upvotes', 0) or 0)),
        'hf_url': f'https://huggingface.co/papers/{aid}',
        'code_urls': code_links(str(paper.get('githubRepo') or entry.get('githubRepo') or '')),
        'hf_daily_date': (entry.get('publishedAt') or '')[:10],
    }


def fetch_daily(day, timeout=30):
    url = ENDPOINT + '?' + urllib.parse.urlencode({'date': day})
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'daily-paper-radar/2.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                data = json.load(response)
            if not isinstance(data, list):
                raise ValueError('Hugging Face Daily Papers 响应不是数组')
            return data
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f'Hugging Face HTTP {exc.code}') from None
            if attempt == 2:
                raise RuntimeError('Hugging Face 拉取失败，请检查网络后重试') from None
            time.sleep(2 ** attempt)


def collect_huggingface(cfg):
    today = datetime.now(timezone.utc).date()
    days = int(cfg.get('lookback_days', 3))
    if not 1 <= days <= 14:
        raise ValueError('huggingface.lookback_days 必须介于 1 和 14')
    papers = {}
    for offset in range(days):
        day = (today - timedelta(days=offset)).isoformat()
        for entry in fetch_daily(day, int(cfg.get('request_timeout_s', 30))):
            paper = normalize_entry(entry)
            if paper is None:
                continue
            previous = papers.get(paper['arxiv_id'])
            if previous is None or paper['hf_upvotes'] > previous['hf_upvotes']:
                papers[paper['arxiv_id']] = paper
        if offset < days - 1:
            time.sleep(1)
    return list(papers.values())
