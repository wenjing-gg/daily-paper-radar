"""飞书多维表格 (Bitable) sink —— 用官方 OpenAPI 把 paper 写入多维表格。

API doc:
  - 获取 tenant_access_token:
    https://open.feishu.cn/document/server-docs/authentication-management/access-token/tenant_access_token_internal
  - 多维表格新增记录（支持批量，单次 ≤ 500 条）:
    https://open.feishu.cn/document/server-docs/docs/bitable-v1/app-table-record/batch_create

profile.sinks 条目示例：
  {
    "type": "feishu_bitable",
    "app_id_env":     "FEISHU_APP_ID",
    "app_secret_env": "FEISHU_APP_SECRET",
    "app_token":      "bascnXXXXXXXXXXXXXXXXXXXXXX",   // 多维表格 URL 里那段
    "table_id":       "tblXXXXXXXXXXXX",               // 表 URL 里 tbl 开头那段
    "filter":         "high+med",                       // 同 notion sink
    "field_map": {
      "短标题":     {"prop": "short_title",      "type": "text"},
      "论文标题":   {"prop": "title",            "type": "text"},
      "链接":       {"prop": "abs_url",          "type": "url"},
      "相关度":     {"prop": "relevance",        "type": "single_select"},
      "命中关键词": {"prop": "matched_keywords", "type": "multi_select"},
      "日期":       {"prop": "_today",           "type": "date"},
      "中文摘要":   {"prop": "summary_cn",       "type": "text"},
      "对我们的启发": {"prop": "insight_for_us", "type": "text"},
      "核心结果":   {"prop": "main_results",     "type": "text"}
    }
  }

field_map 的 key 必须与你飞书表格的字段名一致。`_today` 为占位符，代表 publish 日期。

获取凭据：
  - 飞书开放平台 https://open.feishu.cn → 创建自建应用
  - 应用凭证里有 App ID / App Secret，写到 .env：
  - 权限申请：bitable:app:readonly + bitable:app（建议直接给 bitable:app）
  - 在你的多维表格里：右上「...」→「更多」→「添加协作者」搜应用名加进去
  - app_token 与 table_id 取自表格 URL：
        https://xxx.feishu.cn/base/<app_token>?table=<table_id>&view=...

字段类型映射到飞书：
  text          → 字符串（单行文本 / 多行文本均可）
  url           → {link, text}
  single_select → 字符串（飞书会自动新建未存在的选项；选项名 < 100 字符）
  multi_select  → 字符串数组
  date          → 毫秒级时间戳 (int)
  number        → 数字
"""

from __future__ import annotations

import os
import json
import time
import urllib.request
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from runtime import STATE


FEISHU_BASE = "https://open.feishu.cn/open-apis"
TOKEN_URL = f"{FEISHU_BASE}/auth/v3/tenant_access_token/internal"
MAX_BATCH = 500
MAX_FIELD_TEXT = 9000  # 飞书单字段约 1 万字符上限，留余地


def _abs_url(paper: dict) -> str:
    return paper.get("link") or f"https://arxiv.org/abs/{paper.get('arxiv_id','')}"


def _load_papers(skill_dir: Path) -> list[dict]:
    p = STATE / "output" / "papers.json"
    if not p.exists():
        return []
    return json.loads(p.read_text(encoding="utf-8")).get("papers", [])


def _select_papers(papers: list[dict], filter_str: str) -> list[dict]:
    allowed = {
        "high": {"high"},
        "high+med": {"high", "med"},
        "all": {"high", "med", "low"},
    }.get(filter_str, {"high", "med"})
    return [p for p in papers if p.get("relevance") in allowed]


def _http_post(url: str, body: bytes, headers: dict, timeout: int = 15) -> dict:
    req = urllib.request.Request(url, data=body, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"feishu API {e.code}: {detail}") from e


def _get_tenant_token(app_id: str, app_secret: str) -> str:
    body = json.dumps({"app_id": app_id, "app_secret": app_secret}).encode("utf-8")
    resp = _http_post(TOKEN_URL, body, {"Content-Type": "application/json"})
    if resp.get("code") != 0:
        raise RuntimeError(f"feishu get tenant_access_token failed: {resp}")
    return resp["tenant_access_token"]


def _build_field(spec: dict, paper: dict, today: date):
    prop_key = spec["prop"]
    ftype = spec.get("type", "text")
    if prop_key == "_today":
        value = today
    elif prop_key == "abs_url":
        value = _abs_url(paper)
    else:
        value = paper.get(prop_key)
    if value is None or value == "":
        return None

    if ftype == "text":
        return str(value)[:MAX_FIELD_TEXT]
    if ftype == "url":
        url = str(value)
        return {"link": url, "text": url}
    if ftype == "single_select":
        return str(value)[:99]
    if ftype == "multi_select":
        items = value if isinstance(value, list) else [value]
        return [str(x)[:99] for x in items]
    if ftype == "date":
        if isinstance(value, date):
            dt = datetime(value.year, value.month, value.day, tzinfo=timezone.utc)
        elif isinstance(value, datetime):
            dt = value
        else:
            try:
                dt = datetime.fromisoformat(str(value))
            except ValueError:
                return None
        return int(dt.timestamp() * 1000)
    if ftype == "number":
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
    return None


def _batch_create(token: str, app_token: str, table_id: str,
                  records: list[dict]) -> dict:
    url = (f"{FEISHU_BASE}/bitable/v1/apps/{app_token}"
           f"/tables/{table_id}/records/batch_create")
    body = json.dumps({"records": records}).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json; charset=utf-8",
    }
    resp = _http_post(url, body, headers, timeout=30)
    if resp.get("code") != 0:
        raise RuntimeError(f"feishu batch_create failed: {resp}")
    return resp


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    app_id = os.environ.get(sink_cfg.get("app_id_env", "FEISHU_APP_ID"), "").strip()
    app_secret = os.environ.get(sink_cfg.get("app_secret_env", "FEISHU_APP_SECRET"), "").strip()
    if not (app_id and app_secret):
        raise RuntimeError("feishu_bitable sink: missing FEISHU_APP_ID / FEISHU_APP_SECRET in env")

    app_token = sink_cfg.get("app_token", "").strip()
    table_id = sink_cfg.get("table_id", "").strip()
    if not (app_token and table_id):
        raise RuntimeError("feishu_bitable sink: missing 'app_token' / 'table_id' in profile.sinks entry")

    field_map = sink_cfg.get("field_map") or {}
    if not field_map:
        raise RuntimeError("feishu_bitable sink: empty 'field_map'")

    skill_dir = Path(__file__).resolve().parent.parent.parent
    papers = _load_papers(skill_dir)
    if not papers:
        return {"created": 0, "reason": "no papers.json (skipped)"}

    selected = _select_papers(papers, sink_cfg.get("filter", "high+med"))
    if not selected:
        return {"created": 0, "considered": 0, "total": len(papers)}

    records = []
    for paper in selected:
        fields = {}
        for col_name, spec in field_map.items():
            v = _build_field(spec, paper, today)
            if v is not None:
                fields[col_name] = v
        if fields:
            records.append({"fields": fields})

    token = _get_tenant_token(app_id, app_secret)
    created = 0
    for i in range(0, len(records), MAX_BATCH):
        batch = records[i : i + MAX_BATCH]
        resp = _batch_create(token, app_token, table_id, batch)
        created += len(resp.get("data", {}).get("records", [])) or len(batch)

    return {"created": created, "considered": len(selected), "total": len(papers)}
