#!/usr/bin/env python3
"""通过 OpenAI Chat Completions 或 Anthropic Messages API 生成基于论文证据的分析。失败不提交批次。"""

from __future__ import annotations

import os
import re
import sys
import json
import hashlib
import time
import urllib.request
import urllib.error
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from runtime import ROOT as SKILL_DIR, PROFILE, STATE
RAW = STATE / "output" / "raw_papers.json"
ORGS = STATE / "output" / "orgs.json"
OUT = STATE / "output" / "papers.json"


def log(msg: str) -> None:
    print(f"[enrich_llm] {msg}", file=sys.stderr)


def load_profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8-sig"))


def load_papers() -> tuple[list[dict], dict]:
    if not RAW.exists():
        log(f"no raw_papers.json at {RAW}, nothing to enrich")
        return [], {}
    data = json.loads(RAW.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, {}
    return data.get("papers", []), {k: v for k, v in data.items() if k != "papers"}


def load_orgs() -> dict:
    if not ORGS.exists():
        return {}
    try:
        return json.loads(ORGS.read_text(encoding="utf-8"))
    except Exception:
        return {}


def build_prompt(profile: dict, paper: dict, org: str) -> tuple[str, str]:
    from analysis_prompt import build_analysis_prompt
    return ('你是论文阅读助手，严格按要求返回 JSON。',
            build_analysis_prompt(profile, [paper], {paper.get('arxiv_id'): org}))


_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_response(text: str) -> dict | None:
    """模型可能裹 ```json ... ``` 或前后带说明，尽量挖出 JSON。"""
    text = text.strip()
    # 直接解析
    try:
        return json.loads(text)
    except Exception:
        pass
    # 抠 ```json ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # 抠首个 {...}
    m = _JSON_BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def call_llm(cfg: dict, system: str, user: str) -> str:
    from llm_api import build_request, response_text
    settings, headers, payload = build_request(cfg, system, user)
    req = urllib.request.Request(settings['endpoint'], data=json.dumps(payload).encode('utf-8'), headers=headers, method='POST')
    timeout = int(cfg.get("request_timeout_s", 60))
    last_err = None
    for attempt in range(3):
        from llm_budget import assert_offpeak
        try:
            assert_offpeak()
        except RuntimeError as exc:
            log(str(exc))
            raise
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8")
                data = json.loads(raw)
                return response_text(data, settings['protocol'])
        except urllib.error.HTTPError as e:
            last_err = f"HTTP {e.code}"
            if e.code in (429, 500, 502, 503, 504):
                time.sleep(2 ** attempt)
                continue
            raise RuntimeError(last_err) from e
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = type(e).__name__
            time.sleep(2 ** attempt)
    raise RuntimeError(f"LLM call failed after retries: {last_err}")


def enrich_one(cfg: dict, profile: dict, paper: dict, org: str) -> dict:
    # 单篇 JSON/字段偶发不合规时只重试该篇，不重做整批已经成功的分析。
    for attempt in range(3):
        result = _enrich_once(cfg, profile, paper, org)
        if result.get('_llm_error') != 'ValueError':
            return result
        if attempt < 2:
            log(f"  {paper.get('arxiv_id')} 输出格式校验失败，重试该篇 ({attempt + 1}/2)")
    return result


def _enrich_once(cfg: dict, profile: dict, paper: dict, org: str) -> dict:
    """返回 paper 副本，加入 LLM 字段；失败标记 _llm_error，主流程据此停止发布。"""
    out = dict(paper)
    out.setdefault("affiliations", org or "")
    try:
        system, user = build_prompt(profile, paper, org)
        text = call_llm(cfg, system, user)
        from analysis_prompt import FIELDS, validate_analysis
        parsed = parse_response(text)
        entries = parsed.get('papers') if isinstance(parsed, dict) else None
        if not isinstance(entries, list) or len(entries) != 1:
            raise ValueError('模型必须返回一篇论文的分析')
        result = entries[0]
        validate_analysis(result)
        if result.get('arxiv_id') != paper.get('arxiv_id'):
            raise ValueError('模型返回了不匹配的论文 ID')
        out.update({k: result[k] for k in FIELDS})
        out['analysis_basis'] = 'abstract'
    except Exception as e:
        log(f"  {paper.get('arxiv_id')} FAILED: {type(e).__name__}")
        out["relevance"] = "low"
        out["short_title"] = paper.get("title", "")[:60]
        out["summary_cn"] = ""
        out["insight_for_us"] = ""
        out["_llm_error"] = type(e).__name__
    return out


def resolve_cfg(profile: dict) -> dict | None:
    """统一 API 配置；旧 backend 名称仅作为入口别名保留。"""
    le = profile.get('llm_enrich') or {}
    backend = le.get('backend')
    if backend in ('api', 'openai_compatible'):
        return le.get('api', le.get('openai_compatible', {}))
    if backend is None and le.get('enabled') is True:
        return {k: v for k, v in le.items() if k != 'enabled'}
    return None


def main() -> int:
    profile = load_profile()
    cfg = resolve_cfg(profile)
    if cfg is None:
        log('未启用 API 后端，跳过')
        return 0
    from llm_api import resolve_settings
    settings = resolve_settings(cfg)

    papers, meta = load_papers()
    if not papers:
        log("no papers to enrich")
        return 0

    orgs = load_orgs()
    max_n = int(cfg.get("max_papers", 25))
    if len(papers) > max_n:
        log(f"论文数量 {len(papers)} 超过上限 {max_n}")
        raise RuntimeError("论文数量超过 max_papers，请提高上限后重试，避免静默丢弃论文")

    concurrency = max(1, int(cfg.get("concurrency", 4)))
    log(f"enriching {len(papers)} papers via {settings['model']} ({settings['protocol']}) (concurrency={concurrency})")
    t0 = time.time()

    results: list[dict | None] = [None] * len(papers)
    from runtime import write_json
    cache_path = STATE / 'output/enrich_cache.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {}
    cache_keys = []
    for paper in papers:
        org = orgs.get(paper.get('arxiv_id', ''), '')
        prompt = build_prompt(profile, paper, org)
        cache_keys.append(hashlib.sha256(json.dumps([settings, cfg, prompt], sort_keys=True, ensure_ascii=False).encode()).hexdigest())
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futs = {}
        for i, paper in enumerate(papers):
            saved = cache.get(cache_keys[i])
            if saved and saved.get('arxiv_id') == paper.get('arxiv_id') and not saved.get('_llm_error'):
                from analysis_prompt import validate_analysis
                validate_analysis(saved)
                results[i] = saved
            else:
                futs[ex.submit(enrich_one, cfg, profile, paper, orgs.get(paper.get('arxiv_id', ''), ''))] = i
        for fut in as_completed(futs):
            i = futs[fut]
            try:
                results[i] = fut.result()
                if not results[i].get('_llm_error'):
                    cache[cache_keys[i]] = results[i]
                    write_json(cache_path, cache)
                else:
                    # 记录跨运行失败次数，供下方判断是否降级放行
                    prev = cache.get(cache_keys[i]) or {}
                    fails = int(prev.get('_fails', 0)) + 1
                    cache[cache_keys[i]] = {**papers[i], '_llm_error': results[i]['_llm_error'], '_fails': fails}
                    write_json(cache_path, cache)
            except Exception as e:
                log(f"  task {i} crashed: {e}")
                results[i] = {**papers[i], "_llm_error": type(e).__name__}
                prev = cache.get(cache_keys[i]) or {}
                fails = int(prev.get('_fails', 0)) + 1
                cache[cache_keys[i]] = {**papers[i], '_llm_error': type(e).__name__, '_fails': fails}
                write_json(cache_path, cache)

    out_papers = [r for r in results if r is not None]
    n_high = sum(1 for p in out_papers if p.get("relevance") == "high")
    n_med = sum(1 for p in out_papers if p.get("relevance") == "med")
    n_low = sum(1 for p in out_papers if p.get("relevance") == "low")
    n_err = sum(1 for p in out_papers if p.get("_llm_error"))

    if n_err:
        # 瞬时失败保留批次等待重试；同一篇连续多轮批处理仍失败的视为顽固失败，
        # 降级为低相关（仅列标题）放行，避免单篇模型输出不合规卡死整期日报。
        pending = [i for i, r in enumerate(results)
                   if r is not None and r.get('_llm_error')
                   and int((cache.get(cache_keys[i]) or {}).get('_fails', 0)) < 2]
        if pending:
            raise RuntimeError(f"{len(pending)} 篇摘要失败，保留批次等待重试")
        log(f"{n_err} 篇多轮重试仍失败，降级为低相关放行")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(meta)
    payload["papers"] = out_papers
    payload["llm_enrich"] = {
        "model": settings["model"],
        "protocol": settings["protocol"],
        "n_high": n_high, "n_med": n_med, "n_low": n_low, "n_error": n_err,
        "elapsed_s": round(time.time() - t0, 1),
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"done in {payload['llm_enrich']['elapsed_s']}s · "
        f"high={n_high} med={n_med} low={n_low} err={n_err} · → {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
