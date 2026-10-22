#!/usr/bin/env python3
"""统一推送入口。读 state/output/digest.md，按 profile.sinks 配置依次发到各目标。

profile.sinks 是数组，每个元素 {type, ...}。type 对应 sinks/<type>.py。
任一 sink 失败不影响其他 sink，错误打印到 stderr 后继续。

profile.sinks 缺省时，向后兼容到旧的 FEISHU_WEBHOOK + sync_inbox_to 行为。
"""

from __future__ import annotations

from digest_language import digest_title
from runtime import beijing_today

import os
import sys
import json
import argparse
import importlib
import hashlib
import re
from datetime import date
from pathlib import Path


from runtime import ROOT as SKILL_DIR, PROFILE, STATE, write_json, redact
DEFAULT_DIGEST = STATE / "output" / "digest.md"
RAW_PAPERS = STATE / "output" / "raw_papers.json"

# 这些 sink 会主动通知用户。new_count=0 的空日报时跳过，避免噪声。
# 其他 sink（local_file 等被动落盘）继续跑。
PUSHY_SINKS = {"feishu_bot", "webhook"}


def log(msg: str):
    print(f"[publish] {redact(msg)}", file=sys.stderr)


def load_profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8-sig"))


def legacy_sinks(profile: dict) -> list[dict]:
    """profile.sinks 未配置时，从旧字段推导一组兼容 sink。"""
    out = []
    if os.environ.get("FEISHU_WEBHOOK"):
        out.append({"type": "feishu_bot"})
    sync_to = profile.get("sync_inbox_to")
    if sync_to:
        out.append({"type": "local_file", "dir": sync_to})
    return out


def run_sink(sink_cfg: dict, title: str, markdown: str, profile: dict, today) -> bool:
    sink_type = sink_cfg.get("type")
    if not sink_type:
        log("失败：sink 缺少 type")
        return False
    if sink_cfg.get("enabled") is False:
        log(f"skip {sink_type}: enabled=false")
        return True
    try:
        mod = importlib.import_module(f"sinks.{sink_type}")
    except ImportError as e:
        log(f"unknown sink type '{sink_type}'")
        return False
    try:
        result = mod.send(title, markdown, sink_cfg, profile, today)
        log(f"{sink_type} ok")
        return True
    except Exception as e:
        log(f"{sink_type} FAILED: {type(e).__name__}")
        if sink_type == 'feishu_doc' and isinstance(e, (RuntimeError, ValueError)):
            # 文档 sink 的错误已去除服务端响应原文，仅保留配置提示或数字错误码。
            log(str(e))
        return False


def _load_papers_for_render():
    """加载 papers.json / raw_papers.json，用于按 sink 实时渲染不同版本。"""
    try:
        from render_digest import load_papers, render_digest  # type: ignore
    except ImportError:
        return None, None
    class _Args:
        input = None
        date = None
    papers, _ = load_papers(_Args())
    return papers, render_digest


# 这些 sink 默认推精简版（手机/群聊场景，长正文体验差）。
# 可被 sink_cfg.body = "full" 覆盖。
DEFAULT_CONCISE_SINKS = {"feishu_bot"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", default=None, help="推送标题；缺省取 profile.digest_title + 日期")
    ap.add_argument("--file", default=str(DEFAULT_DIGEST), help="markdown 正文文件（兜底；优先按 sink 实时渲染）")
    ap.add_argument("--date", default=None, help="日期 YYYY-MM-DD，缺省今天")
    ap.add_argument('--resend-bot', action='store_true', help='只向当前群机器人重发上一份日报，不调用模型或写入文档')
    args = ap.parse_args()
    if args.resend_bot:
        if (STATE / 'pending.json').exists():
            raise RuntimeError('存在未完成批次，请先完成该批次再重发群消息')
        if not DEFAULT_DIGEST.exists() or not (STATE / 'output/papers.json').exists():
            raise RuntimeError('没有可重发的已生成日报')
        header = DEFAULT_DIGEST.read_text(encoding='utf-8').splitlines()[0]
        saved_date = re.search(r'\d{4}-\d{2}-\d{2}', header)
        if not saved_date:
            raise RuntimeError('旧日报没有日期，停止重发')
        args.date = saved_date[0]

    sys.path.insert(0, str(Path(__file__).parent))  # 让 sinks 模块可被 import

    profile = load_profile()
    today = date.fromisoformat(args.date) if args.date else beijing_today()
    title = args.title or f"{digest_title(profile)} · {today.isoformat()}"

    body_path = Path(args.file)
    fallback_markdown = body_path.read_text(encoding="utf-8") if body_path.exists() else None

    # 拿 papers 做按 sink 实时渲染（mode=full|concise）
    papers, render_fn = _load_papers_for_render()
    output_mode = (profile.get("output_mode") or "detailed").lower()  # "detailed" | "concise"
    rendered_cache: dict[str, str] = {}

    def render_for(mode: str) -> str:
        if mode not in rendered_cache:
            if papers is not None and render_fn is not None:
                rendered_cache[mode] = render_fn(papers, today, profile, mode=mode)
            else:
                rendered_cache[mode] = fallback_markdown or ""
        return rendered_cache[mode]

    sinks = profile["sinks"] if "sinks" in profile else legacy_sinks(profile)
    if args.resend_bot:
        sinks = [s for s in sinks if s.get('type') == 'feishu_bot' and s.get('enabled', True)]
        if not sinks:
            raise RuntimeError('未配置启用的飞书群机器人')
    if not sinks:
        log("no sinks configured (set profile.sinks); printing digest to stdout")
        print(render_for("full"))
        return

    # 检查 new_count：0 篇时跳过 pushy sink（飞书/webhook 等主动通知），
    # 仅让 local_file 等被动落盘 sink 仍然跑。
    new_count = None
    if RAW_PAPERS.exists():
        try:
            new_count = json.loads(RAW_PAPERS.read_text(encoding="utf-8")).get("new_count")
        except Exception as e:
            log(f"warn: unable to read new_count from {RAW_PAPERS}: {e}")

    log(f"publishing to {len(sinks)} sink(s): {[s.get('type') for s in sinks]} (output_mode={output_mode})")
    receipt_path = STATE / "output/delivery.json"
    receipts = json.loads(receipt_path.read_text(encoding="utf-8")) if receipt_path.exists() else []
    failed = False
    for sc in sinks:
        if sc.get("enabled") is False:
            continue
        if new_count == 0 and sc.get("type") in PUSHY_SINKS:
            log(f"skip {sc.get('type')}: empty digest (new_count=0)")
            continue
        # 决定每个 sink 用哪种 mode：
        #   sink_cfg.body 显式优先；否则 output_mode=concise 时全部精简；
        #   否则按 DEFAULT_CONCISE_SINKS 决定（飞书机器人默认精简，其他默认 full）。
        body_pref = (sc.get("body") or "").lower()
        if body_pref in ("concise", "full"):
            mode = body_pref
        elif output_mode == "concise":
            mode = "concise"
        elif sc.get("type") in DEFAULT_CONCISE_SINKS:
            mode = "concise"
        else:
            mode = "full"
        body = render_for(mode)
        delivery_id = hashlib.sha256(json.dumps([sc, title, body], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        if delivery_id in receipts and not args.resend_bot:
            log(f"skip {sc.get('type')}: 本批次已投递")
            continue
        if run_sink(sc, title, body, profile, today):
            if delivery_id not in receipts:
                receipts.append(delivery_id)
            write_json(receipt_path, receipts)
        else:
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
