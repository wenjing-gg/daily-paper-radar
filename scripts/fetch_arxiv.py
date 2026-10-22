#!/usr/bin/env python3
"""
arxiv 拉取 + 客户端关键词过滤 + 去重。仅依赖 stdlib。

策略：用 arxiv RSS feed（http://export.arxiv.org/rss/<category>）而非 API。
  RSS 限速极宽松（每天几次拉取毫无问题），API 突发会触发数小时 IP 退避。
  RSS 一次返回当日全部新提交（cs.LG ~500/天），客户端用 keywords 过滤。

读：  config/profile.json                  (categories, keywords, include_cross)
写：  state/seen.json                      (已抓 arxiv ID 集合，去重)
      state/output/raw_papers.json        (本次新论文清单)
"""

from __future__ import annotations

import os
import re
import sys
import json
import time
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from runtime import ROOT as SKILL_DIR, PROFILE, STATE
SEEN = STATE / "seen.json"
OUTPUT_DIR = STATE / "output"
RSS_BASE = "https://export.arxiv.org/rss"
USER_AGENT = "daily-paper-radar/1.0"
DC_NS = "{http://purl.org/dc/elements/1.1/}"


def log(msg: str):
    print(f"[fetch] {msg}", file=sys.stderr)


def load_profile() -> dict:
    if not PROFILE.exists():
        log(f"FATAL: profile not found: {PROFILE}")
        sys.exit(2)
    return json.loads(PROFILE.read_text(encoding="utf-8-sig"))


def load_seen() -> set[str]:
    if not SEEN.exists():
        return set()
    try:
        return set(json.loads(SEEN.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_seen(ids: set[str]):
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")


def fetch_rss(category: str) -> bytes:
    """拉一个 category 的 RSS。重试 3 次温和退避（RSS 几乎不限速，主要防短暂网络抖动）。"""
    url = f"{RSS_BASE}/{category}"
    log(f"GET {url}")
    last_err = None
    for attempt, wait in enumerate([5, 10, 30], 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except Exception as e:
            last_err = e
            log(f"  attempt {attempt} failed: {e}; sleep {wait}s")
            time.sleep(wait)
    raise RuntimeError(f"fetch_rss({category}) failed: {last_err}")


def parse_rss(body: bytes, category: str) -> list[dict]:
    """解析 RSS 2.0。每个 item 的 description 形如：
        arXiv:2605.06387v1 Announce Type: new
        Abstract: We propose ...
    """
    root = ET.fromstring(body)
    papers = []
    for item in root.findall(".//item"):
        try:
            title = (item.findtext("title") or "").strip().replace("\n", " ")
            link = (item.findtext("link") or "").strip()
            desc = (item.findtext("description") or "").strip()
            creator = item.findtext(f"{DC_NS}creator") or ""

            m = re.search(r"arXiv:(\d{4}\.\d{4,5})", desc + " " + link)
            arxiv_id = m.group(1) if m else ""
            if not arxiv_id:
                continue

            type_m = re.search(r"Announce Type:\s*(\S+)", desc)
            announce_type = type_m.group(1) if type_m else "new"

            abs_m = re.search(r"Abstract:\s*(.+)$", desc, re.S)
            summary = (abs_m.group(1) if abs_m else "").strip().replace("\n", " ")
            # 干掉残余 HTML 标签
            summary = re.sub(r"<[^>]+>", "", summary)
            creator = re.sub(r"<[^>]+>", "", creator).replace("\n", " ").strip()

            papers.append({
                "arxiv_id": arxiv_id,
                "title": title,
                "authors": creator,
                "summary": summary,
                "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
                "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
                "categories": [category],
                "announce_type": announce_type,
                "published": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            })
        except Exception as e:
            log(f"  parse error: {e}, skip one item")
            continue
    return papers


def keyword_match(paper: dict, keyword_groups: list[list[str]]) -> tuple[bool, list[str]]:
    """每组词需全在 (title + abstract) 里命中。任一组命中即返回 True。
    返回 (是否命中, 命中的关键词组的字符串表示)。
    """
    text = (paper.get("title", "") + " " + paper.get("summary", "")).lower()
    hits = []
    for group_words in keyword_groups:
        if all(w.lower() in text for w in group_words):
            hits.append(" ".join(group_words))
    return (len(hits) > 0, hits)


def parse_keyword_groups(keywords: list[str]) -> list[list[str]]:
    out = []
    for line in keywords:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        out.append([w for w in line.split() if w])
    return out


def main():
    # 兼容旧入口；来源和筛选统一由 fetch_papers 实现。
    from fetch_papers import main as fetch
    fetch()


if __name__ == "__main__":
    main()
