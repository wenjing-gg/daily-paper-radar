#!/usr/bin/env python3
"""
渲染日报：raw_papers.json (+ 可选的 papers.json 含 LLM 中文摘要) → markdown
顶部带会议截稿倒计时。

读：  config/profile.json                  (deadlines, display_name, digest_title, inbox_dir)
      state/output/papers.json            (优先；含 summary_cn / relevance / affiliations)
      state/output/raw_papers.json        (兜底；只有英文 abstract)
写：  state/output/digest.md
      <inbox_dir>/YYYY-MM-DD.md            (沉淀到科研库)
"""

from __future__ import annotations

import os
import sys
import json
import argparse
import re
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from runtime import ROOT as SKILL_DIR, PROFILE, STATE, beijing_today
from digest_language import digest_language, digest_title
OUTPUT_DIR = STATE / "output"


def load_profile() -> dict:
    if not PROFILE.exists():
        print(f"FATAL: profile not found: {PROFILE}", file=sys.stderr)
        sys.exit(2)
    return json.loads(PROFILE.read_text(encoding="utf-8-sig"))


def countdown_lines(today: date, deadlines: list[dict], render_cfg: dict) -> list[str]:
    """生成倒计时行。受 render.deadlines_display 控制：

    - window_days_past:   截稿后多少天内仍显示（默认 3）
    - window_days_future: 未来多少天内才显示（默认 120）
    - max_items:          顶部最多显示几行（默认 5，超过的截掉）
    - mode:               'next_only' = 每个会议只显示「下一个未到期的 deadline」
                          'all_due'   = 把 abstract / full paper 都列出来（旧行为）
    控制顶部噪音、避免遮蔽论文内容。
    """
    en = render_cfg.get("_language") == "en"
    dd = render_cfg.get("deadlines_display") or {}
    window_past = int(dd.get("window_days_past", 3))
    window_future = int(dd.get("window_days_future", 120))
    max_items = int(dd.get("max_items", 5))
    mode = dd.get("mode", "next_only")

    items: list[tuple[int, str]] = []
    for c in deadlines:
        per_conf: list[tuple[int, str, str]] = []
        for key, label in [("abstract_due", "abstract"), ("full_paper_due", "full")]:
            d = c.get(key)
            if not d:
                continue
            try:
                target = date.fromisoformat(d)
            except ValueError:
                continue
            per_conf.append(((target - today).days, label, target.isoformat()))
        if not per_conf:
            continue

        if mode == "next_only":
            future = [x for x in per_conf if x[0] >= 0]
            chosen = [min(future, key=lambda x: x[0])] if future else [max(per_conf, key=lambda x: x[0])]
        else:
            chosen = per_conf

        for delta, label, d_iso in chosen:
            if delta < -window_past or delta > window_future:
                continue
            tag = "" if c.get("official_announced") else (" *(estimated)*" if en else " *(预估)*")
            if delta >= 0:
                line = f"⏳ **{c['name']}** ({label}): **D-{delta}** · {d_iso}{tag}"
            else:
                line = (f"☑️ **{c['name']}** ({label}): {abs(delta)} days ago · {d_iso}{tag}" if en else f"☑️ **{c['name']}** ({label}): 已过 {abs(delta)} 天 · {d_iso}{tag}")
            items.append((delta, line))

    items.sort(key=lambda x: x[0])
    return [s for _, s in items[:max_items]]


def first_of(s: str, sep: str = ",") -> str:
    if not s:
        return ""
    return s.split(sep)[0].strip()


_WD_CN = ["一", "二", "三", "四", "五", "六", "日"]


def announce_window(beijing_today: date, language="zh") -> str | None:
    """展示美东周日至周四的常规公告窗口；不把常规日期当作真实抓取批次证明。"""
    mailing = beijing_today - timedelta(days=1)
    wd = mailing.weekday()  # 0=Mon ... 6=Sun
    if wd in (4, 5):  # 美东周五、周六无常规公告
        return None
    from llm_budget import us_standard_time
    winter = us_standard_time(datetime.combine(beijing_today, datetime.min.time(), tzinfo=timezone.utc))
    hour = '09:00' if winter else '08:00'
    if language == "en":
        return f"📡 Regular arXiv announcement: **{beijing_today.isoformat()} {hour} UTC+08:00** (check the source for actual availability)"
    return f"📡 arXiv 常规公告：北京时间 **{beijing_today.isoformat()} {hour}**（实际公告以来源为准）"



# 默认模板（profile 没配时兜底）
_DEFAULT_RENDER = {
    "show_low_in_digest": False,
    "header_emoji": "📚",
    "relevance_marks": {"high": "🔥🔥🔥", "med": "🔥🔥", "low": "🔥"},
    "max_low": 5,
    "deadlines_display": {
        "window_days_past": 3,
        "window_days_future": 120,
        "max_items": 5,
        "mode": "next_only",
    },
    "labels": {
        "english_title": "📄 Paper",
        "links":         "🔗",
        "summary":       "📝 摘要",
        "insight":       "💡 启发",
    },
    "paper_template": (
        "**{idx}. {short_title}** {relevance_mark}  \n"
        "{label_english_title}：*{english_title}*  \n"
        "{label_links} [arxiv:{arxiv_id}]({abs_url}) · [PDF]({pdf_url}) · {first_author}  \n"
        "**{label_summary}**：{summary_cn}  \n"
        "**{label_insight}**：{insight}"
    ),
    "footer": "*自动生成。*",
}


def get_render_cfg(profile: dict) -> dict:
    """合并 profile.render 和默认值（profile 优先）。"""
    cfg = dict(_DEFAULT_RENDER)
    user = profile.get("render", {}) or {}
    cfg.update({k: v for k, v in user.items() if not k.startswith("_")})
    # 嵌套 dict 也合并
    for k in ("relevance_marks", "labels", "deadlines_display"):
        merged = dict(_DEFAULT_RENDER[k])
        merged.update(user.get(k, {}) or {})
        cfg[k] = merged
    cfg['_language'] = digest_language(profile)
    if cfg['_language'] == 'en':
        cfg['labels'] = {'english_title': '📄 Paper', 'links': '🔗', 'summary': '📝 Summary', 'insight': '💡 Implications', **(user.get('labels') or {})}
        if 'paper_template' not in user:
            cfg['paper_template'] = cfg['paper_template'].replace('：', ': ')
        if 'footer' not in user:
            cfg['footer'] = '*Automatically generated.*'
    return cfg


def institution_label(p, language="zh"):
    """仅展示有一作来源的机构，优先采用本批模型给出的中文简称。"""
    raw = (p.get('first_author_affiliation') or '').strip()
    if not raw:
        return ''
    org = (p.get('affiliations') or '').strip()
    if not org or org in ('?', '未知', '未核实'):
        org = raw
    if language == 'en':
        return re.sub(r'https?://\S+', '', org).strip(' /')
    aliases = {
        'University of Illinois at Chicago': '伊利诺伊大学芝加哥分校',
        'University of Science and Technology of China': '中科大',
        'University of California, Riverside': '加州大学河滨分校',
        'Carnegie Mellon University': '卡内基梅隆大学',
        'Shanghai AI Laboratory': '上海AI Lab', 'Tsinghua University': '清华',
        'Peking University': '北大', 'Zhejiang University': '浙大',
        'Sun Yat-sen University': '中山大学', 'Seoul National University': '首尔大学',
        'Virginia Tech': '弗吉尼亚理工', 'Yuanbao Team, Tencent': '腾讯元宝',
        'Visa Research': 'Visa研究院', 'Meta AI': 'Meta',
    }
    org = re.sub(r'https?://\S+', '', org)
    for original, short in aliases.items():
        org = org.replace(original, short)
    return re.sub(r'[；;]\s*', '/', org).strip(' /')


def clean_title(p, today=None, language="zh"):
    idea = (p.get('short_title') or p.get('title') or ('Untitled paper' if language == 'en' else '未命名论文')).strip()
    idea = re.sub(r'^\d{2}\.\d{2}(?:\.\d{2})?-arxiv-[^-]+-', '', idea)
    # 日期代表日报收录日，不将 RSS 抓取日冒充论文发表日。
    day = (today or beijing_today()).strftime('%y.%m.%d')
    venue = (p.get('venue') or '').strip() if p.get('venue_source') else ''
    return '-'.join(part for part in (day, venue, institution_label(p, language), idea)
                    if part and part not in ('?', '未知', '未核实'))


def render_paper_block(p: dict, idx: int, render_cfg: dict, mode: str = "full", today=None) -> str:
    en = render_cfg.get("_language") == "en"
    def tr(zh, english):
        return english if en else zh
    arxiv_id = p.get("arxiv_id", "")
    # 群消息也保留完整摘要，不用一句话概览替代方法介绍。
    summary = p.get("summary_cn") or p.get("summary") or tr("*(摘要待补全)*", "*(Summary unavailable)*")
    insight = (p.get("insight_for_us") or "").strip() or tr("*(启发待补全)*", "*(Implications unavailable)*")
    fields = {
        "idx": idx,
        "arxiv_id": arxiv_id,
        "abs_url": p.get("abs_url") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""),
        "pdf_url": p.get("pdf_url") or (f"https://arxiv.org/pdf/{arxiv_id}.pdf" if arxiv_id else ""),
        "english_title": p.get("title", "(no title)").strip(),
        "short_title": clean_title(p, today, render_cfg.get("_language", "zh")),
        "first_author": first_of(p.get("authors", "")) or tr("*未知*", "*Unknown*"),
        "summary_cn": summary,
        "insight": insight,
        "relevance_mark": render_cfg["relevance_marks"].get(p.get("relevance", ""), ""),
    }
    # label_xxx 占位符也注入
    for k, v in render_cfg["labels"].items():
        fields[f"label_{k}"] = v
    try:
        block = render_cfg["paper_template"].format(**fields)
        details = []
        if p.get('relevance') or p.get('summary_cn'):
            basis = {'abstract': tr('摘要分析', 'Abstract only'), 'fulltext': tr('全文材料分析（未独立复现）', 'Full-text materials (not independently replicated)')}.get(p.get('analysis_basis'), tr('分析依据未记录', 'Analysis basis not recorded'))
            details.append(f"**{tr('阅读依据', 'Reading basis')}**: {basis}")
        links = p.get('code_urls', [])
        if links:
            details.append(tr('💻 **代码**：', '💻 **Code**: ') + ' · '.join(f'[{tr("仓库", "Repository")} {i}]({url})' for i, url in enumerate(links, 1)))
        if p.get('hf_url'):
            details.append(f"🤗 [{tr('社区讨论', 'Discussion')}]({p['hf_url']}) · {p.get('hf_upvotes', 0)} {tr('票（抓取时）', 'votes at fetch time')}")
        if mode == 'full' and p.get('evidence'):
            details.append(f"**{tr('证据', 'Evidence')}**: {p['evidence']}")
        if p.get('limitations'):
            details.append(f"**{tr('局限 / 待核实', 'Limitations / To verify')}**: {p['limitations']}")
        if p.get('reading_priority'):
            priority = {'deep_read': tr('建议精读', 'Read in depth'), 'skim': tr('建议略读', 'Skim'), 'skip': tr('暂不阅读', 'Skip for now')}.get(p['reading_priority'], '')
            details.append(f"**{priority}**: {p.get('reading_reason', '')}")
        return block + ('  \n' + '  \n'.join(details) if details else '')
    except KeyError as e:
        return f"[render error: missing placeholder {e}]\n{fields}"


def render_digest(papers: list[dict], today: date, profile: dict, mode: str = "full") -> str:
    """渲染 markdown digest。mode='full' 走完整正文；mode='concise' 保留完整摘要、减少独立分析栏目。"""
    language = digest_language(profile)
    en = language == "en"
    def tr(zh, english):
        return english if en else zh
    title = digest_title(profile)
    deadlines = profile.get("deadlines", [])
    rc = get_render_cfg(profile)

    header = f"**{rc['header_emoji']} {title} · {today.isoformat()}{tr('（北京时间）', ' (UTC+08:00)')}**".strip()
    blocks = [header]
    models = list(dict.fromkeys(p.get('analysis_model') for p in papers if p.get('analysis_model')))
    if models:
        blocks.append(tr('🤖 总结模型：', '🤖 Model: ') + ', '.join(models))
    elif any(p.get('relevance') for p in papers):
        blocks.append(tr('🤖 总结模型：旧批次未记录', '🤖 Model: not recorded in this batch'))

    aw = announce_window(today, language) if any("arxiv" in p.get("sources", ["arxiv"]) for p in papers) else None
    if aw:
        blocks.append(aw)

    cd = countdown_lines(today, deadlines, rc)
    if cd:
        blocks.append("\n".join(cd))

    if not papers:
        blocks.append(tr(f"今日（{today.isoformat()}）未发现新的相关论文。", f"No new matching papers found for {today.isoformat()}."))
    else:
        # 检测 LLM 增强是否缺失（papers 都没有 relevance / summary_cn 字段）
        enriched = sum(1 for p in papers if p.get("relevance") or p.get("summary_cn"))
        if enriched == 0:
            blocks.append(
                tr("**原始论文列表**：本次未调用模型，以下为标题与原始摘要。", "**Raw paper list**: no model was called; original titles and abstracts follow.")
            )
        order = {"high": 0, "med": 1, "low": 2}
        papers = sorted(papers, key=lambda p: (order.get(p.get("relevance", ""), 9), {"deep_read": 0, "skim": 1, "skip": 2}.get(p.get("reading_priority"), 3), -p.get("hf_upvotes", 0)))
        n_high = sum(1 for p in papers if p.get("relevance") == "high")
        n_med = sum(1 for p in papers if p.get("relevance") == "med")
        n_low = sum(1 for p in papers if p.get("relevance") == "low")

        show_low = bool(rc["show_low_in_digest"])
        shown = papers if show_low else [p for p in papers if p.get("relevance") != "low"]
        hidden_low = [p for p in papers if p.get("relevance") == "low"][:max(0, int(rc.get("max_low", 5)))]
        if show_low:
            shown = [p for p in papers if p.get("relevance") != "low"] + hidden_low

        # 用 relevance_marks 拼概要行，避免硬编码 high/med/low 字样
        m_h = rc["relevance_marks"].get("high", "high")
        m_m = rc["relevance_marks"].get("med", "med")
        m_l = rc["relevance_marks"].get("low", "low")
        summary_line = (tr(f"本期分析 **{len(papers)}** 篇候选  ", f"Analyzed **{len(papers)}** candidates  ") +
                        f"·  {m_h.strip()} ×{n_high}  "
                        f"·  {m_m.strip()} ×{n_med}  "
                        f"·  {m_l.strip()} ×{n_low}"
                        + ("" if show_low else tr(f"  ·  低相关仅展示 {len(hidden_low)} 篇标题链接", f"  ·  Showing {len(hidden_low)} low-relevance links")))
        blocks.append(summary_line)

        max_detailed = int(rc.get('max_detailed', 10))
        overflow, shown = shown[max_detailed:], shown[:max_detailed]
        if enriched:
            basis = "包含全文分析，具体依据见各篇说明" if any(p.get("analysis_basis") == "fulltext" for p in papers) else "论文摘要"
            if en:
                blocks.append('Analysis basis is shown per paper. Votes indicate community interest, not quality. Reading recommendations require further verification.')
            else:
                blocks.append(f"分析依据：{basis}；票数是社区关注度，不代表质量。阅读建议供进一步核查与选择。")
        for i, p in enumerate(shown, 1):
            blocks.append('---')
            blocks.append(render_paper_block(p, i, rc, mode=mode, today=today))

        if overflow:
            blocks.append(tr('**更多候选（本期未展开）**\n', '**More candidates (not expanded)**\n') + '\n'.join(
                f"- [{clean_title(p, today, language)}]({p.get('abs_url', '')})" for p in overflow))
        if not show_low and hidden_low:
            low_lines = [tr(f"**▼ 低相关 {len(hidden_low)} 篇（仅列标题链接）**", f"**▼ Low relevance: {len(hidden_low)} papers (links only)**")]
            base = len(shown)
            for j, p in enumerate(hidden_low, 1):
                st = clean_title(p, today, language)
                low_lines.append(f"{base + j}. [{st}]({p.get('abs_url','')})")
            blocks.append("\n".join(low_lines))

    if rc.get("footer"):
        blocks.append("---\n" + rc["footer"])
    return "\n\n".join(blocks)


def resolve_inbox(profile: dict) -> Path:
    inbox = profile.get("inbox_dir") or str(STATE / "inbox")
    p = Path(os.path.expanduser(inbox))
    if not p.is_absolute():
        p = (SKILL_DIR / inbox).resolve()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _read_papers(path: Path) -> tuple[list[dict], dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return data, {}
    papers = data.get('papers', [])
    model = data.get('llm_enrich', {}).get('model')
    if model:
        papers = [{**p, 'analysis_model': p.get('analysis_model') or model} for p in papers]
    return papers, data


def load_papers(args) -> tuple[list[dict], dict]:
    """优先 LLM 补全后的 papers.json，兜底 raw_papers.json。
    防过期：如果 papers.json 的 id 集合与当天 raw_papers.json 不一致，
    认为是上一次的残留，丢弃，改用 raw_papers.json（无中文摘要但不会重推）。
    """
    if args.input:
        return _read_papers(Path(args.input))

    raw_path = OUTPUT_DIR / "raw_papers.json"
    enriched_path = OUTPUT_DIR / "papers.json"

    raw_papers, raw_meta = ([], {})
    if raw_path.exists():
        raw_papers, raw_meta = _read_papers(raw_path)
    raw_ids = {p.get("arxiv_id") for p in raw_papers}

    if enriched_path.exists():
        ep, em = _read_papers(enriched_path)
        ep_ids = {p.get("arxiv_id") for p in ep}
        # 只要 enriched 是 raw 的子集（LLM 可能 prefilter 掉一些）就采用
        if ep_ids and ep_ids.issubset(raw_ids):
            return ep, em
        print(f"[render] discarding stale papers.json (ids mismatch raw_papers.json)", file=sys.stderr)

    return raw_papers, raw_meta


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", help="覆盖输入；缺省按 papers.json → raw_papers.json 顺序找")
    ap.add_argument("--date", help="日期覆盖 YYYY-MM-DD")
    args = ap.parse_args()

    profile = load_profile()
    papers, meta = load_papers(args)
    today = date.fromisoformat(args.date) if args.date else beijing_today()

    digest_md = render_digest(papers, today, profile)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    digest_path = OUTPUT_DIR / "digest.md"
    digest_path.write_text(digest_md, encoding="utf-8")

    inbox = resolve_inbox(profile)
    inbox_file = inbox / f"{today.isoformat()}.md"
    inbox_file.write_text(digest_md, encoding="utf-8")

    print(f"[render] digest: {digest_path}")
    print(f"[render] inbox:  {inbox_file}")
    print(f"[render] papers: {len(papers)}")


if __name__ == "__main__":
    main()
