"""通用 HTTP POST sink。给任意接收方推送 JSON。

profile.sinks 条目示例：
  {
    "type": "webhook",
    "url":  "https://example.com/api/inbox",
    "method": "POST",
    "headers": {"Authorization": "Bearer ${MY_TOKEN}"},
    "payload_template": {
      "title": "{title}",
      "date":  "{date}",
      "body_md": "{markdown}"
    }
  }

payload_template 里支持 {title} {date} {markdown} 占位符。
headers 值里 ${ENV_VAR} 会被环境变量替换。
"""

from __future__ import annotations

import os
import re
import json
import urllib.request


_ENV_RE = re.compile(r"\$\{([A-Z0-9_]+)\}")


def _expand_env(s: str) -> str:
    return _ENV_RE.sub(lambda m: os.environ.get(m.group(1), ""), s)


def _fill(value, ctx):
    if isinstance(value, str):
        return value.format(**ctx)
    if isinstance(value, dict):
        return {k: _fill(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_fill(v, ctx) for v in value]
    return value


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    url = sink_cfg.get("url")
    if not url:
        raise RuntimeError("webhook sink requires 'url'")
    method = sink_cfg.get("method", "POST").upper()

    ctx = {"title": title, "date": today.isoformat(), "markdown": markdown}
    payload = _fill(sink_cfg.get("payload_template") or {"title": "{title}", "markdown": "{markdown}"}, ctx)

    headers = {"Content-Type": "application/json"}
    for k, v in (sink_cfg.get("headers") or {}).items():
        headers[k] = _expand_env(v) if isinstance(v, str) else v

    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=headers,
        method=method,
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return {"status": resp.status, "body": body[:500]}
