# -*- coding: utf-8 -*-
"""切块：markdown → 语义块。按标题层级切大段，超长段再按滑窗切。

vault 只读；本模块不写任何文件。
"""
import re
from config import MAX_CHARS, OVERLAP, MIN_CHARS

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

def _split_long(text: str) -> list[str]:
    """无标题结构的超长段：按滑窗硬切，重叠 OVERLAP。"""
    if len(text) <= MAX_CHARS:
        return [text] if len(text.strip()) >= MIN_CHARS else []
    out, step = [], MAX_CHARS - OVERLAP
    for i in range(0, len(text), step):
        piece = text[i:i + MAX_CHARS]
        if len(piece.strip()) < MIN_CHARS and out:
            # 尾部碎片并入前一块
            out[-1] += piece
        else:
            out.append(piece)
        if i + MAX_CHARS >= len(text):
            break
    return [p for p in (x.strip() for x in out) if p]

def chunk_markdown(text: str) -> list[tuple[str, str]]:
    """两级策略：先按标题行分段（携带父级标题路径做上下文前缀），长段再滑窗。

    返回 [(标题路径, 块文本), ...]——section 与正文分离，不再靠解析前缀还原。
    """
    lines = text.splitlines()
    sections: list[tuple[str, list[str]]] = []   # (标题路径, 行列表)
    cur_path, cur_lines = "", []
    for ln in lines:
        m = HEADING_RE.match(ln)
        if m:
            level = len(m.group(1))
            if cur_lines:
                sections.append((cur_path, cur_lines))
            title = m.group(2).strip()
            cur_path = title if level == 1 else f"{cur_path} › {title}" if cur_path else title
            cur_lines = []
        else:
            cur_lines.append(ln)
    if cur_lines:
        sections.append((cur_path, cur_lines))

    out: list[tuple[str, str]] = []
    for path, lns in sections:
        body = "\n".join(lns).strip()
        if not body:
            continue
        for piece in _split_long(body):
            out.append((path, piece))
    return out

def chunk_note(rel_path: str, raw: str) -> list[dict]:
    """整篇笔记的块列表。frontmatter 单独成块（元数据检索用）。"""
    fm = ""
    body = raw
    if raw.startswith("---"):
        parts = raw.split("---", 2)
        if len(parts) == 3:
            fm, body = parts[1].strip(), parts[2]
    out = []
    if fm:
        out.append({"text": "[frontmatter]\n" + fm[:MAX_CHARS], "section": "frontmatter"})
    for section, piece in chunk_markdown(body):
        text = f"[{section}]\n{piece}" if section else piece
        out.append({"text": text[:MAX_CHARS + len(section) + 2], "section": section})
    return out
