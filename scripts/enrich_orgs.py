#!/usr/bin/env python3
"""
Resolve first-author affiliation by downloading the arxiv LaTeX source.

The arxiv API and Semantic Scholar both have poor affiliation coverage for
freshly-posted papers, because authors rarely fill the API's optional
affiliation field and S2 needs time to ingest. The LaTeX source, on the other
hand, almost always contains the affiliation (it's printed on the title page).

For each paper in state/output/raw_papers.json, fetch
    https://arxiv.org/e-print/<id>
which returns either a tar.gz of the source tree or a single .tex.gz, scan
the .tex files for known institution names and \\affiliation / \\institute
commands, write the result to state/output/orgs.json:

    { "<arxiv_id>": "Tsinghua University" }   # missing -> ""

Read by render_digest.py (and consumed by Claude in step 2 of SKILL.md).

Stdlib-only. Throttled to 1 req/s out of politeness.
"""

from __future__ import annotations

import io
import re
import sys
import json
import gzip
import time
import tarfile
import urllib.request
import urllib.error
from pathlib import Path

from runtime import ROOT as SKILL_DIR, PROFILE, STATE
RAW = STATE / "output" / "raw_papers.json"
OUT = STATE / "output" / "orgs.json"
USER_AGENT = "daily-paper-radar/1.0"
PER_PAPER_GAP_S = 1.0     # courtesy gap between requests
HEAD_BYTES = 30000        # only the first 30 KB of each tex file holds the title block

# Known institution short-names. Match wins by first occurrence in the head of
# the main tex file, so order matters: more specific entries first when there
# is overlap (e.g. "Shanghai AI Lab" before "Shanghai").
KNOWN_ORGS = [
    # English
    ("Massachusetts Institute of Technology", "MIT"),
    ("MIT CSAIL", "MIT"),
    ("Stanford University", "Stanford"),
    ("UC Berkeley", "Berkeley"), ("University of California, Berkeley", "Berkeley"),
    ("Carnegie Mellon", "CMU"),
    ("Princeton University", "Princeton"),
    ("Harvard University", "Harvard"), ("Yale University", "Yale"),
    ("Cornell University", "Cornell"),
    ("Duke University", "Duke"),
    ("University of Pennsylvania", "Penn"),
    ("Johns Hopkins", "JHU"),
    ("Northwestern University", "Northwestern"),
    ("University of Michigan", "UMich"),
    ("University of Illinois", "UIUC"),
    ("University of Texas", "UT Austin"),
    ("Georgia Institute of Technology", "Georgia Tech"),
    ("New York University", "NYU"),
    ("Columbia University", "Columbia"),
    ("Washington University", "WUSTL"),
    ("AstraZeneca", "AstraZeneca"),
    ("Pfizer", "Pfizer"), ("Novartis", "Novartis"), ("GSK", "GSK"),
    ("University of Washington", "UW"),
    ("University of Toronto", "Toronto"),
    ("ETH Zurich", "ETH"), ("EPFL", "EPFL"),
    ("University of Oxford", "Oxford"), ("University of Cambridge", "Cambridge"),
    ("Imperial College", "Imperial"),
    ("UCLA", "UCLA"), ("UCSD", "UCSD"), ("UCL", "UCL"),
    ("National University of Singapore", "NUS"),
    ("Nanyang Technological University", "NTU"),
    ("Hong Kong University of Science and Technology", "HKUST"),
    ("Chinese University of Hong Kong", "CUHK"),
    ("University of Hong Kong", "HKU"),
    # Companies
    ("Google DeepMind", "Google DeepMind"), ("DeepMind", "DeepMind"),
    ("Google Research", "Google"),
    ("Microsoft Research", "Microsoft"),
    ("Meta AI", "Meta"), ("FAIR", "Meta"),
    ("Anthropic", "Anthropic"),
    ("OpenAI", "OpenAI"),
    ("NVIDIA", "NVIDIA"),
    ("IBM Research", "IBM"),
    ("Apple", "Apple"),
    ("Salesforce", "Salesforce"),
    ("Tencent", "腾讯"), ("Tencent AI Lab", "腾讯"),
    ("Alibaba", "阿里"), ("Alibaba Group", "阿里"), ("DAMO Academy", "阿里达摩院"),
    ("ByteDance", "字节"), ("Bytedance", "字节"),
    ("Huawei", "华为"), ("Huawei Noah", "华为诺亚"), ("Noah's Ark Lab", "华为诺亚"),
    ("Baidu", "百度"),
    ("Meituan", "美团"),
    ("JD.com", "京东"), ("JD AI", "京东"),
    ("Xiaohongshu", "小红书"), ("RedNote", "小红书"),
    ("Kuaishou", "快手"), ("XiaoIce", "小冰"),
    ("DeepSeek", "DeepSeek"), ("Moonshot AI", "Moonshot"),
    ("Zhipu", "智谱"), ("Qwen Team", "通义千问"),
    ("MiniMax", "MiniMax"), ("01.AI", "零一万物"),
    # Chinese universities (English then PRC short)
    ("Tsinghua University", "清华"),
    ("Peking University", "北大"),
    ("Shanghai Jiao Tong", "上海交大"),
    ("Fudan University", "复旦"),
    ("Zhejiang University", "浙大"),
    ("University of Science and Technology of China", "中科大"),
    ("Chinese Academy of Sciences", "中科院"),
    ("Renmin University", "人大"),
    ("Beihang", "北航"),
    ("Beijing Institute of Technology", "北理工"),
    ("Sun Yat-sen", "中山大学"),
    ("Nanjing University", "南大"),
    ("Harbin Institute of Technology", "哈工大"),
    ("Wuhan University", "武大"),
    ("Huazhong University of Science", "华科"),
    ("Tongji University", "同济"),
    ("Xi'an Jiaotong", "西交大"),
    ("Shanghai AI Lab", "上海AI Lab"), ("Shanghai Artificial Intelligence Laboratory", "上海AI Lab"),
    ("Beijing Academy of Artificial Intelligence", "BAAI"), ("BAAI", "BAAI"),
    # Other regions
    ("KAIST", "KAIST"), ("Seoul National University", "SNU"),
    ("Yonsei University", "延世"), ("POSTECH", "POSTECH"),
    ("University of Tokyo", "东大"), ("Kyoto University", "京大"),
    ("Tel Aviv University", "TAU"), ("Hebrew University", "Hebrew"),
    ("Mila", "Mila"), ("Vector Institute", "Vector"),
    ("Allen Institute", "AI2"), ("AI2", "AI2"),
    ("Cohere", "Cohere"), ("Mistral", "Mistral"),
]


def log(msg: str):
    print(f"[orgs] {msg}", file=sys.stderr)


def open_no_proxy() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def fetch_source(arxiv_id: str, opener) -> bytes | None:
    """GET https://arxiv.org/e-print/<id>. Returns raw bytes (gzipped tar or .gz).
    None means no source available (some papers are PDF-only)."""
    url = f"https://arxiv.org/e-print/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(req, timeout=30) as r:
            return r.read()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        log(f"  {arxiv_id}: HTTP {e.code}")
        return None
    except Exception as e:
        log(f"  {arxiv_id}: fetch error {e}")
        return None


def fetch_pdf_first_page(arxiv_id: str, opener) -> str:
    """Fallback for PDF-only submissions: download the PDF, extract first-page
    text, return it. Requires pypdf (`pip install pypdf`); returns "" if pypdf
    is missing or parsing fails. Does not persist the PDF on disk."""
    try:
        import pypdf
    except ImportError:
        log("  pypdf not installed; skip PDF fallback (pip install pypdf to enable)")
        return ""
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        log(f"  PDF fetch failed: {e}")
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        if not reader.pages:
            return ""
        return reader.pages[0].extract_text() or ""
    except Exception as e:
        log(f"  PDF parse failed: {e}")
        return ""


_GENERIC_ORG = re.compile(
    r"\b("
    r"(?:[A-Z][a-zA-Z.]+ )?University(?: of [A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)?)?"
    r"|[A-Z][a-zA-Z]+ Institute(?: of [A-Z][a-zA-Z]+)?"
    r"|[A-Z][a-zA-Z]+ (?:AI )?(?:Lab|Laboratory|Research)"
    r")"
)


def first_org_from_plain_text(text: str) -> str:
    """PDF text dump: KNOWN_ORGS first (high precision), then a generic
    `XXX University / Institute / Lab` regex over the title block."""
    head = text[:5000]
    head_lower = head.lower()
    for needle, short in KNOWN_ORGS:
        if needle.lower() in head_lower:
            return short
    m = _GENERIC_ORG.search(head)
    if m:
        return m.group(1)[:40]
    return ""


def extract_tex(blob: bytes) -> list[str]:
    """Return list of decoded .tex contents found in the blob.
    Handles both tar.gz (multi-file) and plain .gz (single file)."""
    # Try as tar.gz first
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            out = []
            for m in tar.getmembers():
                if not m.isfile():
                    continue
                if not m.name.lower().endswith((".tex", ".ltx")):
                    continue
                f = tar.extractfile(m)
                if f is None:
                    continue
                try:
                    out.append(f.read().decode("utf-8", errors="ignore"))
                except Exception:
                    continue
            return out
    except tarfile.ReadError:
        pass
    # Fall back to single-file gzip
    try:
        text = gzip.decompress(blob).decode("utf-8", errors="ignore")
        return [text]
    except Exception:
        return []


def pick_main(texts: list[str]) -> str:
    """Concatenate the most-likely main file plus any short ancillary ones.
    The main file is the first one containing \\documentclass; if none,
    take the largest."""
    if not texts:
        return ""
    main = next((t for t in texts if r"\documentclass" in t), None)
    if main is None:
        main = max(texts, key=len)
    # Prepend any other tex that contains \author or \affiliation, in case
    # the title block was split out.
    extras = [
        t for t in texts
        if t is not main and (r"\author" in t or r"\affiliation" in t or r"\institute" in t)
    ]
    return "\n".join([main] + extras)


def strip_latex(s: str) -> str:
    """Remove common LaTeX cruft so org names compare cleanly."""
    s = re.sub(r"\\(?:textit|textbf|textsc|texttt|emph|sf|tt|it|bf|rm){?", "", s)
    s = re.sub(r"\\[a-zA-Z]+\*?", " ", s)
    s = s.replace("{", " ").replace("}", " ").replace("~", " ").replace("\\", " ")
    s = re.sub(r"\s+", " ", s)
    return s.strip(" ,;.")


def title_block(text: str) -> str:
    """Restrict the search to LaTeX preamble + title page.
    Bibitems and `\\cite{openai2023}` style references live after `\\bibliography`,
    far past `\\begin{document}`, so this kills nearly all false positives where
    a famous lab is merely cited rather than authoring."""
    begin = text.find(r"\begin{document}")
    if begin == -1:
        return text[:HEAD_BYTES]
    # preamble + first ~5000 chars after \begin{document} for the title block
    return text[:begin + 5000]


_AFFIL_CMDS = re.compile(
    r"\\(?:author|affiliation|affil|institute|inst|address)"
    r"\s*(?:\[[^]]*\])?"
    r"\s*\{((?:[^{}]|\{[^{}]*\})*)\}",   # one level of nested {}
    re.S,
)


def author_block(text: str) -> str:
    """Concatenate the contents of all \\author / \\affiliation-family commands
    in the title block. This is the strictest possible scope for `who is this
    paper from` -- it excludes \\thanks acknowledgements, citations, and
    related-work mentions of other labs."""
    region = title_block(text)
    chunks = _AFFIL_CMDS.findall(region)
    if chunks:
        return strip_latex("\n".join(chunks))
    # Fall back to whole title block if no command matched (unusual templates)
    return strip_latex(region)


def first_org(text: str) -> str:
    region = author_block(text)
    region_lower = region.lower()
    for needle, short in KNOWN_ORGS:
        if needle.lower() in region_lower:
            return short
    # Last resort: explicit \affiliation{...} / \institute{...} text content
    for cmd in [r"\\affiliation\s*\{([^}]{3,120})\}",
                r"\\institute\s*\{([^}]{3,120})\}",
                r"\\affil(?:iation)?\s*\[[^]]*\]\s*\{([^}]{3,120})\}"]:
        m = re.search(cmd, title_block(text))
        if m:
            v = strip_latex(m.group(1))
            parts = [p.strip() for p in re.split(r"[,;]", v) if p.strip()]
            for p in parts:
                if any(w[0].isupper() for w in p.split()):
                    return p[:40]
            if parts:
                return parts[0][:40]
    return ""


def main():
    if not RAW.exists():
        log(f"missing {RAW}; run fetch_arxiv.py first")
        sys.exit(2)
    papers = json.loads(RAW.read_text()).get("papers", [])
    if not papers:
        OUT.write_text("{}")
        log("no papers, wrote empty orgs.json")
        return

    # Resume if we already have partial data
    orgs: dict[str, str] = {}
    if OUT.exists():
        try:
            orgs = json.loads(OUT.read_text())
        except Exception:
            orgs = {}

    todo = [p for p in papers if p["arxiv_id"] not in orgs]
    log(f"{len(papers)} total · {len(todo)} to fetch · {len(papers) - len(todo)} cached")

    opener = open_no_proxy()
    for i, p in enumerate(todo, 1):
        aid = p["arxiv_id"]
        org = ""
        method = "src"
        blob = fetch_source(aid, opener)
        if blob is not None:
            texts = extract_tex(blob)
            if texts:
                org = first_org(pick_main(texts))

        # PDF fallback: triggered when source missing, source had no .tex,
        # or source was present but no recognizable institution turned up.
        if not org:
            method = "pdf"
            page1 = fetch_pdf_first_page(aid, opener)
            if page1:
                org = first_org_from_plain_text(page1)

        orgs[aid] = org
        log(f"  [{i}/{len(todo)}] {aid}: {org or '(unknown)'} [{method}]")

        OUT.write_text(json.dumps(orgs, ensure_ascii=False, indent=2))
        if i < len(todo):
            time.sleep(PER_PAPER_GAP_S)

    found = sum(1 for v in orgs.values() if v)
    log(f"done · resolved {found}/{len(orgs)}")


if __name__ == "__main__":
    main()
