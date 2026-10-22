"""合并 arXiv RSS 与 Hugging Face 精选论文，按 ID 去重并保留来源。"""
from __future__ import annotations
from datetime import datetime, timezone
import json
import time
from runtime import PROFILE, STATE, write_json
from fetch_arxiv import fetch_rss, parse_rss, parse_keyword_groups, keyword_match
from fetch_huggingface import collect_huggingface
from paper_metadata import enrich_metadata
from source_gate import apply_gate, load_policy


def source_config(profile):
    sources = profile.get('sources')
    if sources is None:
        return {'arxiv': {'enabled': True}, 'huggingface': {'enabled': False}}
    if not isinstance(sources, dict) or set(sources) - {'arxiv', 'huggingface'}:
        raise ValueError('sources 只支持 arxiv 和 huggingface 配置对象')
    if any(not isinstance(v, dict) for v in sources.values()):
        raise ValueError('每个来源必须是包含 enabled 的配置对象')
    if not any(isinstance(v, dict) and v.get('enabled', False) for v in sources.values()):
        raise ValueError('至少启用一个论文来源')
    return sources


def collect_arxiv(profile):
    result = {}
    categories = profile.get('categories') or ['cs.LG', 'cs.CL', 'cs.AI', 'stat.ML']
    for index, category in enumerate(categories):
        for paper in parse_rss(fetch_rss(category), category):
            aid = paper['arxiv_id']
            paper['sources'] = ['arxiv']
            if aid in result:
                result[aid]['categories'] = sorted(set(result[aid]['categories'] + paper['categories']))
            else:
                result[aid] = paper
        if index < len(categories) - 1:
            time.sleep(2)
    return list(result.values())


def select_and_merge(arxiv, hf, profile, seen=None):
    cfg = source_config(profile).get('huggingface', {})
    groups = parse_keyword_groups(profile.get('keywords', []))
    merged = {}
    for paper in arxiv:
        kind = paper.get('announce_type', 'new')
        if kind != 'new' and not (kind == 'cross' and profile.get('include_cross', True)) and not (kind == 'replace' and profile.get('include_replace', False)):
            continue
        match, hits = keyword_match(paper, groups)
        if match:
            merged[paper['arxiv_id']] = {**paper, 'matched_keywords': hits}
    candidates = []
    for paper in hf:
        if paper['arxiv_id'] in (seen or set()):
            continue
        if paper['hf_upvotes'] < int(cfg.get('min_upvotes', 0)):
            continue
        match, hits = keyword_match(paper, groups)
        if cfg.get('keyword_filter', False) and not match:
            continue
        candidates.append({**paper, 'matched_keywords': hits})
    candidates.sort(key=lambda p: (-p['hf_upvotes'], p['arxiv_id']))
    limit = int(cfg.get('max_papers', 20))
    if limit < 1:
        raise ValueError('huggingface.max_papers 必须为正整数')
    pool = candidates if profile.get('source_gate', {}).get('enabled', False) else candidates[:limit]
    for paper in pool:
        aid = paper['arxiv_id']
        previous = merged.get(aid)
        if previous:
            merged[aid] = {**previous, **{k: v for k, v in paper.items() if k.startswith('hf_') or k == 'code_urls'},
                           'sources': ['arxiv', 'huggingface']}
        else:
            merged[aid] = paper
    return sorted(merged.values(), key=lambda p: (-p.get('hf_upvotes', 0), p['arxiv_id']))


def screen_candidates(papers, profile):
    gate = profile.get('source_gate', {})
    before_gate = len(papers)
    if gate.get('enabled', False):
        budget = int(gate.get('max_metadata_candidates', 100))
        if not 1 <= budget <= 500:
            raise ValueError('max_metadata_candidates 必须为 1–500')
        papers = papers[:budget]
    if profile.get('paper_metadata', {}).get('enabled', False):
        for i, paper in enumerate(papers):
            papers[i] = enrich_metadata(paper)
            if gate.get('enabled') and gate.get('pdf_affiliation_fallback', False):
                from affiliation_pdf import enrich_pdf_affiliation
                papers[i] = enrich_pdf_affiliation(papers[i], profile)
            if i < len(papers) - 1:
                time.sleep(3)
    papers, gate_report = apply_gate(papers, gate)
    if gate.get('enabled', False):
        gate_report['not_evaluated_due_to_budget'] = max(0, before_gate - gate_report['evaluated'])
        # HF 配额在机构筛选之后生效，被排除论文不占用名额。
        hf_limit = int(profile.get('sources', {}).get('huggingface', {}).get('max_papers', 20))
        hf_count = 0
        retained = []
        for paper in papers:
            if 'huggingface' in paper.get('sources', []) and 'arxiv' not in paper.get('sources', []):
                if hf_count >= hf_limit:
                    continue
                hf_count += 1
            retained.append(paper)
        papers = retained
        gate_report['selected_for_analysis'] = len(papers)
    return papers, gate_report


def main():
    profile = json.loads(PROFILE.read_text(encoding='utf-8-sig'))
    sources = source_config(profile)
    gate = profile.get('source_gate', {})
    if gate.get('enabled', False):
        load_policy(gate)  # 抓取前校验，缺失或损坏的名单不得绕过准入。
        if not profile.get('paper_metadata', {}).get('enabled', False):
            raise ValueError('启用来源筛选必须启用 paper_metadata，不能无机构证据筛选')
    import sys
    if '--refilter-saved' in sys.argv:
        path = STATE / 'output/raw_papers.json'
        payload = json.loads(path.read_text(encoding='utf-8'))
        papers, report = screen_candidates(payload['papers'], profile)
        payload.update(papers=papers, new_count=len(papers), source_gate=report)
        write_json(path, payload)
        return
    arxiv = collect_arxiv(profile) if sources.get('arxiv', {}).get('enabled', False) else []
    hf = collect_huggingface(sources['huggingface']) if sources.get('huggingface', {}).get('enabled', False) else []
    seen_path = STATE / 'seen.json'
    seen = set(json.loads(seen_path.read_text(encoding='utf-8'))) if seen_path.exists() else set()
    selected = select_and_merge(arxiv, hf, profile, seen)
    papers = [p for p in selected if p['arxiv_id'] not in seen]
    papers, gate_report = screen_candidates(papers, profile)
    payload = {
        'source_gate': gate_report,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'sources': [k for k, v in sources.items() if v.get('enabled', False)],
        'source_counts': {'arxiv': len(arxiv), 'huggingface': len(hf)},
        'total_fetched': len({p['arxiv_id'] for p in arxiv + hf}),
        'after_keyword_filter': len(selected), 'new_count': len(papers), 'papers': papers,
    }
    write_json(STATE / 'output/raw_papers.json', payload)
    print(f'NEW_PAPERS={len(papers)}' if papers else 'NO_NEW_PAPERS')


if __name__ == '__main__':
    main()
