"""Obsidian sink — 通过 Obsidian Local REST API 插件写笔记。

依赖（用户侧一次性）：
  1. 在 Obsidian 里安装社区插件 "Local REST API" (coddingtonbear)
  2. 启用插件，在设置里复制 API Key，写到 .env：
  3. 默认监听 https://127.0.0.1:27124 (自签证书)

profile.sinks 条目示例：
  {
    "type": "obsidian",
    "host": "127.0.0.1",
    "port": 27124,
    "https": true,
    "verify_tls": false,                    // 自签证书要置 false
    "token_env": "OBSIDIAN_TOKEN",
    "vault_path": "Papers/arxiv/{date}.md",   // vault 内相对路径
    "front_matter": {                       // 可选 YAML
      "tags": ["arxiv", "daily"]
    },
    "create_only": false                    // true=已存在则不覆盖
  }

接口契约（Local REST API v3.x）：
  PUT  /vault/<urlencoded path>   body=markdown 原文   →  创建或整文覆盖
  GET  /vault/<urlencoded path>                         →  200 已存在 / 404 不存在
"""

from __future__ import annotations

import os
import ssl
import urllib.parse
import urllib.request


def _front_matter(fm: dict) -> str:
    if not fm:
        return ""
    lines = ["---"]
    for k, v in fm.items():
        if isinstance(v, list):
            lines.append(f"{k}:")
            for item in v:
                lines.append(f"  - {item}")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---")
    lines.append("")
    return "\n".join(lines)


def _opener(verify_tls: bool):
    handlers = [urllib.request.ProxyHandler({})]   # 绕系统代理（127.0.0.1 不走代理）
    if not verify_tls:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        handlers.append(urllib.request.HTTPSHandler(context=ctx))
    return urllib.request.build_opener(*handlers)


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    host = sink_cfg.get("host", "127.0.0.1")
    port = int(sink_cfg.get("port", 27124))
    https = bool(sink_cfg.get("https", True))
    verify_tls = bool(sink_cfg.get("verify_tls", False))
    token = os.environ.get(sink_cfg.get("token_env", "OBSIDIAN_TOKEN"))
    if not token:
        raise RuntimeError("obsidian sink: missing token (set OBSIDIAN_TOKEN or sink_cfg.token_env)")

    vault_path_tmpl = sink_cfg.get("vault_path", "{date}.md")
    vault_path = vault_path_tmpl.format(date=today.isoformat(), title=title).lstrip("/")
    encoded_path = urllib.parse.quote(vault_path, safe="/")

    scheme = "https" if https else "http"
    url = f"{scheme}://{host}:{port}/vault/{encoded_path}"

    body = (_front_matter(sink_cfg.get("front_matter") or {}) + markdown).encode("utf-8")

    opener = _opener(verify_tls)

    if sink_cfg.get("create_only"):
        # 探测存在性
        head = urllib.request.Request(url, method="GET",
                                      headers={"Authorization": f"Bearer {token}"})
        try:
            with opener.open(head, timeout=5) as r:
                if r.status == 200:
                    return {"path": vault_path, "skipped": "already exists"}
        except urllib.error.HTTPError as e:
            if e.code != 404:
                raise

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "text/markdown",
        },
        method="PUT",
    )
    with opener.open(req, timeout=15) as resp:
        return {"path": vault_path, "url": url, "status": resp.status, "bytes": len(body)}
