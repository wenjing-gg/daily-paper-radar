#!/usr/bin/env python3
"""
Pull arXiv LaTeX source / PDF for relevance-tagged papers and extract the
parts that matter for understanding the method:

    Abstract → Introduction → Method/Approach/Contributions → Conclusion

The output is plain text per paper at state/output/fulltext/<id>.md. The
LLM in SKILL.md step 2b reads these when profile.deep_read.enabled = true,
and uses them to write summary_cn / insight_for_us with method-level
detail instead of abstract-only paraphrase.

Selection policy (read from profile.deep_read):
    apply_to:  "high"     // "high" | "high+med" | "all"
    max_chars: 30000      // hard truncate per paper
    sections:  ["abstract","introduction","method","approach",
                "contribution","conclusion","discussion"]

If a paper has no LaTeX source, fall back to the PDF (first 8 pages) using
pypdf. If neither works, the paper is silently skipped — the LLM should
still write its summary from the abstract.

Stdlib + optional pypdf. Throttled 1 req/s.
"""

from __future__ import annotations

import io
import re
import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from enrich_orgs import (    # type: ignore
    fetch_source, extract_tex, pick_main, open_no_proxy, log as _log,
)
import tarfile, gzip


def extract_tex_dict(blob: bytes) -> dict[str, str]:
    """Like extract_tex but keeps filename → content mapping.
    Needed because many papers split body into `chapters/*.tex` via \\input{}."""
    out: dict[str, str] = {}
    try:
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            for m in tar.getmembers():
                if not m.isfile() or not m.name.lower().endswith((".tex", ".ltx")):
                    continue
                f = tar.extractfile(m)
                if f is None:
                    continue
                try:
                    out[m.name] = f.read().decode("utf-8", errors="ignore")
                except Exception:
                    continue
        return out
    except tarfile.ReadError:
        pass
    try:
        return {"main.tex": gzip.decompress(blob).decode("utf-8", errors="ignore")}
    except Exception:
        return {}


_INPUT_RE = re.compile(r"\\(?:input|include)\s*\{([^}]+)\}")


def _resolve_path(ref: str, files: dict[str, str]) -> str | None:
    """LaTeX \\input/\\include arg → matching key in files dict.
    Tries ref, ref+.tex, basename(ref), basename+.tex."""
    candidates = [ref, ref + ".tex"]
    base = ref.split("/")[-1]
    candidates += [base, base + ".tex"]
    keys_lower = {k.lower(): k for k in files}
    keys_basename = {k.split("/")[-1].lower(): k for k in files}
    for c in candidates:
        cl = c.lower()
        if cl in keys_lower:
            return keys_lower[cl]
        if cl in keys_basename:
            return keys_basename[cl]
    return None


def expand_inputs(main_tex: str, files: dict[str, str], max_depth: int = 4) -> str:
    """Recursively expand \\input{x} / \\include{x} with the referenced file's
    content. Stops after max_depth to guard against cycles."""
    text = main_tex
    for _ in range(max_depth):
        if not _INPUT_RE.search(text):
            break
        def repl(m):
            ref = m.group(1).strip()
            key = _resolve_path(ref, files)
            return files.get(key, "") if key else ""
        text = _INPUT_RE.sub(repl, text)
    return text


def pick_main_expanded(files: dict[str, str]) -> str:
    """Find main tex (has \\documentclass) and inline all \\input/\\include."""
    if not files:
        return ""
    main_name = next((n for n, t in files.items() if r"\documentclass" in t), None)
    if main_name is None:
        main_name = max(files, key=lambda n: len(files[n]))
    return expand_inputs(files[main_name], files)


from runtime import ROOT as SKILL_DIR, PROFILE, STATE
RAW = STATE / "output" / "raw_papers.json"
RELEVANCE = STATE / "output" / "relevance.json"
OUT_DIR = STATE / "output" / "fulltext"

PER_PAPER_GAP_S = 1.0
DEFAULT_SECTIONS = [
    "abstract", "introduction", "background",
    "method", "methods", "approach", "model", "framework",
    "preliminaries", "problem", "contribution", "contributions",
    "analysis", "theoretical",
    "conclusion", "conclusions", "discussion", "summary",
]
DEFAULT_MAX_CHARS = 30000
DEFAULT_PDF_PAGES = 8


def log(msg: str):
    print(f"[fulltext] {msg}", file=sys.stderr)


# ---- LaTeX cleanup ----------------------------------------------------------

_COMMENT_RE = re.compile(r"(?<!\\)%.*?$", re.M)
_VERBATIM_RE = re.compile(r"\\begin\{verbatim\}.*?\\end\{verbatim\}", re.S)
_FIGURE_RE = re.compile(r"\\begin\{figure\*?\}.*?\\end\{figure\*?\}", re.S)
_TABLE_RE = re.compile(r"\\begin\{table\*?\}.*?\\end\{table\*?\}", re.S)
_ALGO_RE = re.compile(r"\\begin\{algorithm\*?\}.*?\\end\{algorithm\*?\}", re.S)
_DISPLAY_MATH_RE = re.compile(r"\\begin\{(?:equation|align|gather|eqnarray)\*?\}.*?"
                              r"\\end\{(?:equation|align|gather|eqnarray)\*?\}", re.S)
_CITE_RE = re.compile(r"\\(?:cite[a-z]*|ref|eqref|autoref|cref|Cref|label)\s*"
                      r"(?:\[[^]]*\])?\s*\{[^}]*\}")
_FORMATTING_CMDS = re.compile(
    r"\\(?:textbf|textit|textsc|texttt|emph|underline|footnote|thanks|cmidrule|"
    r"hline|midrule|toprule|bottomrule|noindent|smallskip|medskip|bigskip|"
    r"vspace|hspace|small|footnotesize|scriptsize|tiny|large|Large|LARGE|huge|"
    r"vbox|hbox|left|right|big|Big|bigg|Bigg|qquad|quad)\s*\{?"
)
_GENERIC_CMD = re.compile(r"\\[a-zA-Z@]+\*?\s*(?:\[[^]]*\])?\s*")
_BRACES_RE = re.compile(r"[{}]")
_WS_RE = re.compile(r"[ \t]+\n|\n{3,}|\s{3,}")


def clean_latex(s: str) -> str:
    s = _COMMENT_RE.sub("", s)
    s = _VERBATIM_RE.sub("[verbatim omitted]", s)
    s = _FIGURE_RE.sub("[figure omitted]", s)
    s = _TABLE_RE.sub("[table omitted]", s)
    s = _ALGO_RE.sub("[algorithm omitted]", s)
    s = _DISPLAY_MATH_RE.sub(lambda m: " [display math: "
                              + re.sub(r"\s+", " ", m.group(0)[:200]) + "...] ", s)
    s = _CITE_RE.sub("", s)
    s = _FORMATTING_CMDS.sub("", s)
    s = _GENERIC_CMD.sub(" ", s)
    s = _BRACES_RE.sub("", s)
    s = s.replace("~", " ").replace("\\", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()


# ---- Section extraction -----------------------------------------------------

_SECTION_RE = re.compile(
    r"\\(?:section|subsection|subsubsection|chapter)\*?\s*"
    r"(?:\[[^]]*\])?\s*\{([^}]+)\}"
)
_ABSTRACT_RE = re.compile(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", re.S)


def extract_abstract(main_tex: str) -> str:
    m = _ABSTRACT_RE.search(main_tex)
    if m:
        return clean_latex(m.group(1))
    # \abstract{...} variant
    m = re.search(r"\\abstract\s*\{((?:[^{}]|\{[^{}]*\})*)\}", main_tex, re.S)
    if m:
        return clean_latex(m.group(1))
    return ""


def split_sections(main_tex: str) -> list[tuple[str, str]]:
    """Return [(section_title, body_raw), ...] from \\begin{document} onward.
    Body is raw LaTeX, not cleaned."""
    start = main_tex.find(r"\begin{document}")
    if start == -1:
        start = 0
    end = main_tex.find(r"\bibliography")
    if end == -1:
        end = main_tex.find(r"\begin{thebibliography}")
    if end == -1:
        end = len(main_tex)
    body = main_tex[start:end]

    matches = list(_SECTION_RE.finditer(body))
    if not matches:
        return []
    sections: list[tuple[str, str]] = []
    for i, m in enumerate(matches):
        title = m.group(1).strip()
        s = m.end()
        e = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        sections.append((title, body[s:e]))
    return sections


def is_relevant_section(title: str, allow: list[str]) -> bool:
    t = clean_latex(title).strip().lower()
    return any(kw in t for kw in allow)


def is_appendix_marker(title: str) -> bool:
    return re.search(r"\bappendix\b", title.lower()) is not None


def assemble_fulltext(main_tex: str, allow: list[str], max_chars: int) -> str:
    abstract = extract_abstract(main_tex)
    out: list[str] = []
    if abstract:
        out.append(f"## Abstract\n\n{abstract}")

    seen_appendix = False
    for title, body in split_sections(main_tex):
        if is_appendix_marker(title):
            seen_appendix = True
            break
        if not is_relevant_section(title, allow):
            continue
        cleaned = clean_latex(body)
        if not cleaned:
            continue
        clean_title = clean_latex(title).strip()
        out.append(f"## {clean_title}\n\n{cleaned}")

    text = "\n\n".join(out)
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n\n[truncated at {max_chars} chars]"
    if seen_appendix and "[truncated" not in text:
        text += "\n\n[appendix sections omitted]"
    return text


# ---- PDF fallback -----------------------------------------------------------

def fetch_pdf_text(arxiv_id: str, opener, max_pages: int) -> str:
    try:
        import pypdf
    except ImportError:
        log(f"  pypdf not installed; can't fall back to PDF for {arxiv_id}")
        return ""
    import urllib.request as ur
    url = f"https://arxiv.org/pdf/{arxiv_id}"
    req = ur.Request(url, headers={"User-Agent": "daily-paper-radar/1.0"})
    try:
        with opener.open(req, timeout=60) as r:
            data = r.read()
    except Exception as e:
        log(f"  {arxiv_id}: PDF fetch failed: {e}")
        return ""
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
    except Exception as e:
        log(f"  {arxiv_id}: PDF parse failed: {e}")
        return ""
    pages = []
    for i, page in enumerate(reader.pages[:max_pages]):
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            continue
    return "\n\n".join(pages).strip()


# ---- Main -------------------------------------------------------------------

def load_profile() -> dict:
    return json.loads(PROFILE.read_text(encoding="utf-8-sig"))


def select_papers(profile: dict) -> list[dict]:
    if not RAW.exists():
        log(f"missing {RAW}; run fetch_arxiv.py first")
        sys.exit(2)
    papers = json.loads(RAW.read_text()).get("papers", [])
    if not papers:
        return []
    apply_to = (profile.get("deep_read") or {}).get("apply_to", "high")
    if apply_to == "all":
        return papers
    if not RELEVANCE.exists():
        log(f"no relevance.json — LLM hasn't tagged yet. "
            f"Either set deep_read.apply_to='all' or run LLM relevance tagging first.")
        return []
    rel = json.loads(RELEVANCE.read_text())  # {arxiv_id: "high"|"med"|"low"}
    if apply_to == "high+med":
        keep = {"high", "med"}
    else:
        keep = {"high"}
    return [p for p in papers if rel.get(p["arxiv_id"]) in keep]


def main():
    profile = load_profile()
    cfg = profile.get("deep_read") or {}
    if not cfg.get("enabled"):
        log("deep_read disabled in profile (set deep_read.enabled=true to turn on)")
        return
    sections = cfg.get("sections") or DEFAULT_SECTIONS
    max_chars = int(cfg.get("max_chars", DEFAULT_MAX_CHARS))
    max_pdf_pages = int(cfg.get("pdf_max_pages", DEFAULT_PDF_PAGES))

    papers = select_papers(profile)
    if not papers:
        log("no papers selected for deep read; done")
        return
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    opener = open_no_proxy()

    log(f"{len(papers)} papers to deep-read · max_chars={max_chars} · sections={len(sections)} kw")
    n_src, n_pdf, n_fail = 0, 0, 0

    for i, p in enumerate(papers, 1):
        aid = p["arxiv_id"]
        out_path = OUT_DIR / f"{aid}.md"
        if out_path.exists() and out_path.stat().st_size > 500:
            log(f"  [{i}/{len(papers)}] {aid}: cached ({out_path.stat().st_size}B)")
            continue

        text = ""
        method = ""
        blob = fetch_source(aid, opener)
        if blob is not None:
            files = extract_tex_dict(blob)
            if files:
                main_tex = pick_main_expanded(files)
                text = assemble_fulltext(main_tex, sections, max_chars)
                if text and len(text) > 800:
                    method = "src"

        if not method:
            pdf_text = fetch_pdf_text(aid, opener, max_pdf_pages)
            if pdf_text:
                # Crude section trim on PDF: drop everything after 'References' if present
                cut = re.search(r"\n[Rr]eferences\s*\n", pdf_text)
                if cut:
                    pdf_text = pdf_text[:cut.start()]
                text = pdf_text[:max_chars]
                method = "pdf"

        if not method:
            n_fail += 1
            log(f"  [{i}/{len(papers)}] {aid}: FAILED (no source, no pdf)")
        else:
            # Write with a small header so the LLM knows the provenance
            header = (f"# {p.get('title', '')}\n\n"
                      f"- arxiv: {aid}\n"
                      f"- source: {method}\n"
                      f"- chars: {len(text)}\n\n---\n\n")
            out_path.write_text(header + text, encoding="utf-8")
            if method == "src":
                n_src += 1
            else:
                n_pdf += 1
            log(f"  [{i}/{len(papers)}] {aid}: {len(text)}B [{method}]")

        if i < len(papers):
            time.sleep(PER_PAPER_GAP_S)

    log(f"done · src={n_src} · pdf={n_pdf} · failed={n_fail}")


if __name__ == "__main__":
    main()
