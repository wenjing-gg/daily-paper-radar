"""飞书自定义机器人 webhook（interactive 卡片）。

profile.sinks 条目示例：
  {
    "type": "feishu_bot",
    "webhook_env": "FEISHU_WEBHOOK",
    "secret_env":  "FEISHU_SECRET",
    "card_color":  "blue"
  }

webhook_env / secret_env 只指定环境变量名称，配置中禁止存储凭据。
"""

from __future__ import annotations

import os
import json
import time
import hmac
import base64
import hashlib
import urllib.request


def _gen_sign(secret: str, ts: int) -> str:
    h = hmac.new(f"{ts}\n{secret}".encode("utf-8"), digestmod=hashlib.sha256)
    return base64.b64encode(h.digest()).decode("utf-8")


def _split_into_elements(body_md: str) -> list[str]:
    """把 digest markdown 切成"每篇 paper 一个 element"。

    飞书 markdown element 内的长段落会被 UI 折叠为"...点击查看更多"，必须把
    每篇 paper 拆成独立 element 才不被折叠。
    切分边界：以 `**N. [` 开头的 paper 条目；header（含倒计时、命中统计）合并
    为第一个 element；末尾 footer 单独 element。
    """
    paras = body_md.split("\n\n")
    elements: list[str] = []
    header_buf: list[str] = []
    in_papers = False

    for p in paras:
        ps = p.strip()
        if not ps:
            continue
        # paper 条目识别：以 **\d+. [ 开头
        if ps.startswith("**") and ps[2:].split(".", 1)[0].isdigit():
            if header_buf and not in_papers:
                elements.append("\n\n".join(header_buf))
                header_buf = []
            in_papers = True
            elements.append(p)
        elif ps.startswith("**▼") or ps.startswith("---"):
            # 折叠 low 列表 或 footer
            if header_buf and not in_papers:
                elements.append("\n\n".join(header_buf))
                header_buf = []
            elements.append(p)
        else:
            if in_papers:
                # 落到 papers 之后又出现非 paper 段（罕见）：单独 element
                elements.append(p)
            else:
                header_buf.append(p)

    if header_buf and not in_papers:
        elements.append("\n\n".join(header_buf))
    return elements


def _build_card(title: str, body_md: str, color: str) -> dict:
    parts = _split_into_elements(body_md)
    # 飞书一张卡片对 element 数量上限实测 ~50；超过就拆 fallback 单 element
    if len(parts) > 50:
        parts = [body_md]
    elements: list[dict] = []
    for c in parts:
        if c.strip().startswith('---'):
            elements.append({'tag': 'hr'})
            c = c.strip()[3:].strip()
            if not c:
                continue
        elements.append({"tag": "markdown", "content": c})
    return {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": title},
                "template": color,
            },
            "elements": elements,
        },
    }


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    webhook = os.environ.get(sink_cfg.get("webhook_env", "FEISHU_WEBHOOK"))
    secret = os.environ.get(sink_cfg.get("secret_env", "FEISHU_SECRET")) or None
    color = sink_cfg.get("card_color", "blue")

    if not webhook:
        raise RuntimeError("飞书 webhook 环境变量未配置")

    payload = _build_card(title, markdown, color)
    if secret:
        ts = int(time.time())
        payload["timestamp"] = str(ts)
        payload["sign"] = _gen_sign(secret, ts)

    req = urllib.request.Request(
        webhook,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    # 飞书在国内：绕开系统 https_proxy（如 Clash），否则代理挂时 Connection refused
    opener = urllib.request.build_opener() if sink_cfg.get("use_proxy", False) else urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if data.get("code", data.get("StatusCode", -1)) != 0:
        raise RuntimeError("飞书拒绝推送，请检查机器人签名、关键词、IP 白名单及卡片大小")
    return data
