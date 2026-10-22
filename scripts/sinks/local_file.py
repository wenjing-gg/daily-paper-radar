"""写日报到本地目录（Obsidian vault / 任意 markdown 文件夹通用）。

profile.sinks 条目示例：
  {
    "type": "local_file",
    "dir":  "~/Documents/Obsidian/Inbox/daily-paper-radar",
    "filename": "{date}.md",            // 可选；默认 {date}.md
    "front_matter": {                    // 可选；YAML front matter
      "tags": ["arxiv", "daily"],
      "source": "daily-paper-radar"
    },
    "mirror_notes": true                 // 可选；默认 true。
                                          // true = 同时把 state/output/notes/*.md
                                          // (per-high-paper 独立笔记) 镜像到
                                          // <dir>/notes/<id>.md
  }

filename 支持 {date} {title} 占位符。dir 支持 ~ 展开。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from runtime import STATE


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


def send(title: str, markdown: str, sink_cfg: dict, profile: dict, today) -> dict:
    dir_str = sink_cfg.get("dir")
    if not dir_str:
        raise RuntimeError("local_file sink requires 'dir'")
    target_dir = Path(os.path.expanduser(dir_str))
    target_dir.mkdir(parents=True, exist_ok=True)

    fname_tmpl = sink_cfg.get("filename", "{date}.md")
    fname = fname_tmpl.format(date=today.isoformat(), title=title)
    target = target_dir / fname

    body = _front_matter(sink_cfg.get("front_matter") or {}) + markdown
    target.write_text(body, encoding="utf-8")

    result = {"path": str(target), "bytes": len(body)}

    # 镜像 high paper 的独立 markdown 笔记（由 LLM 在 pass 2c 生成到
    # state/output/notes/）到 <dir>/notes/<id>.md，方便用户直接读
    if sink_cfg.get("mirror_notes", True):
        skill_dir = Path(__file__).resolve().parent.parent.parent
        notes_src = STATE / "output" / "notes"
        if notes_src.exists():
            notes_dst = target_dir / "notes"
            notes_dst.mkdir(parents=True, exist_ok=True)
            mirrored = []
            for note in notes_src.glob("*.md"):
                dst = notes_dst / note.name
                shutil.copy2(note, dst)
                mirrored.append(note.name)
            if mirrored:
                result["mirrored_notes"] = len(mirrored)
    return result
