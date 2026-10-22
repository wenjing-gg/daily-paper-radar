#!/usr/bin/env python3
"""保留旧 Claude 入口；提示词与跨平台执行由共享模块实现。"""

from __future__ import annotations

import json
import re
import sys

def build_prompt(profile: dict, papers: list[dict], orgs: dict) -> str:
    from analysis_prompt import build_analysis_prompt
    return build_analysis_prompt(profile, papers, orgs)


_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_BLOCK_RE = re.compile(r"\{.*\}", re.DOTALL)


def parse_json(text: str) -> dict | None:
    text = text.strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = _FENCE_RE.search(text)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = _BLOCK_RE.search(text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def main():
    # 保留旧入口，统一使用跨平台实现。
    from enrich_cli import main as run
    run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
