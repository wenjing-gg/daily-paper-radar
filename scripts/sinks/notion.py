"""Notion sink —— 用官方 Notion API 把 high/med paper 写到指定 database。

Notion API: https://developers.notion.com/reference

每篇 paper 在 database 里新增一个 page；page 的 properties 字段映射可配。
Database 的列必须由用户预先在 Notion 里建好（脚本不会自动建列），
否则 `properties` 校验会失败、API 返回 400。

profile.sinks 条目示例：
  {
    "type": "notion",
    "token_env": "NOTION_TOKEN",                // 从 env 读取 integration token
    "database_id": "abcd1234abcd1234abcd1234",  // 32 字符或带连字符的 UUID
    "filter": "high+med",                       // high / high+med / all（默认 high+med）
    "version": "2022-06-28",                    // Notion API 版本头（可选）
    "field_map": {                              // 你 Notion database 里实际的列名 → 论文字段
      "Title":       {"prop": "short_title",      "type": "title"},
      "Paper":       {"prop": "title",            "type": "rich_text"},
      "URL":         {"prop": "abs_url",          "type": "url"},
      "Relevance":   {"prop": "relevance",        "type": "select"},
      "Keywords":    {"prop": "matched_keywords", "type": "multi_select"},
      "Date":        {"prop": "_today",           "type": "date"},
      "Summary":     {"prop": "summary_cn",       "type": "rich_text"},
      "Insight":     {"prop": "insight_for_us",   "type": "rich_text"},
      "MainResults": {"prop": "main_results",    "type": "rich_text"}
    }
  }

field_map 的 key 必须与 Notion database 的列名严格一致（大小写敏感）。
其中 `_today` 是特殊占位符，代表 publish 的日期。

获取 token：https://www.notion.so/my-integrations 创建 integration，把 Internal
Integration Token 写进 .env：
再在你的 database 页面右上 "..." → Connections → 选这个 integration。
否则 API 返回 "object_not_found"。

获取 database_id：在 Notion 里打开 database 页面，URL 形如
  https://www.notion.so/<workspace>/<database_id>?v=<view_id>
取 ? 之前最后一段（32 字符 hex）即可，不需要连字符。
"""

from __future__ import annotations

import os
import json
import urllib.request
import urllib.error
from datetime import date
from pathlib import Path
from runtime import STATE


NOTION_API = "https://api.notion.com/v1"
DEFAULT_VERSION = "2022-06-28"
MAX_RICH_TEXT_LEN = 1900  # Notion 单条 rich_text 上限 2000 字符，留点余量


def _load_papers(skill_dir: Path) -> list[dict]:
    p = STATE / "output" / "papers.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("papers", [])


def _abs_url(paper: dict) -> str:
    return paper.get("link") or f"https://arxiv.org/abs/{paper.get('arxiv_id','')}"


def _select_papers(papers: list[dict], filter_str: str) -> list[dict]:
    allowed = {
        "high": {"high"},
        "high+med": {"high", "med"},
        "all": {"high", "med", "low"},
    }.get(filter_str, {"high", "med"})
    return [p for p in papers if p.get("relevance") in allowed]


def _build_property(spec: dict, paper: dict, today: date) -> dict | None:
    """根据 field_map 单项 spec 生成 Notion property payload。"""
    prop_key = spec["prop"]
    prop_type = spec["type"]
    if prop_key == "_today":
        value = today.isoformat()
    elif prop_key == "abs_url":
        value = _abs_url(paper)
    else:
        value = paper.get(prop_key)
    if value is None or value == "":
        return None

    def _rich(text: str) -> list[dict]:
        text = str(text)[:MAX_RICH_TEXT_LEN]
        return [{"type": "text", "text": {"content": text}}]

    if prop_type == "title":
        return {"title": _rich(value)}
    if prop_type == "rich_text":
        return {"rich_text": _rich(value)}
    if prop_type == "url":
        return {"url": str(value)}
    if prop_type == "select":
        return {"select": {"name": str(value)}}
    if prop_type == "multi_select":
        items = value if isinstance(value, list) else [value]
        return {"multi_select": [{"name": str(x)[:99]} for x in items]}
    if prop_type == "date":
        return {"date": {"start": str(value)}}
    if prop_type == "number":
        try:
            return {"number": float(value)}
        except (TypeError, ValueError):
            return None
    return None


def _create_page(token: str, version: str, database_id: str,
                 properties: dict) -> dict:
    body = json.dumps({
        "parent": {"database_id": database_id},
        "properties": properties,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{NOTION_API}/pages",
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Notion-Version": version,
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Notion API {e.code}: {detail}") from e


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    token_env = sink_cfg.get("token_env", "NOTION_TOKEN")
    token = os.environ.get(token_env, "").strip()
    if not token:
        raise RuntimeError(f"notion sink: missing token (set {token_env} in .env)")

    database_id = sink_cfg.get("database_id", "").replace("-", "").strip()
    if not database_id:
        raise RuntimeError("notion sink: missing 'database_id' in profile.sinks entry")

    field_map = sink_cfg.get("field_map") or {}
    if not field_map:
        raise RuntimeError("notion sink: empty 'field_map' (define Notion column → paper field)")

    version = sink_cfg.get("version", DEFAULT_VERSION)

    skill_dir = Path(__file__).resolve().parent.parent.parent
    papers = _load_papers(skill_dir)
    if not papers:
        return {"created": 0, "reason": "no papers.json (skipped)"}

    selected = _select_papers(papers, sink_cfg.get("filter", "high+med"))

    created = 0
    failed = []
    for paper in selected:
        props = {}
        for col_name, spec in field_map.items():
            v = _build_property(spec, paper, today)
            if v is not None:
                props[col_name] = v
        try:
            _create_page(token, version, database_id, props)
            created += 1
        except Exception as e:
            failed.append((paper.get("arxiv_id"), str(e)[:200]))

    result = {"created": created, "considered": len(selected), "total": len(papers)}
    if failed:
        result["failed"] = failed[:5]
    return result
