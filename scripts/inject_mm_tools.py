# -*- coding: utf-8 -*-
"""inject_mm_tools.py — 给部署版 rag-obsidian server.py 注入多模态检索工具（幂等）。

multimodal_search：查 data/multimodal.db（PDF/PPTX 页描述/文字层/复盘），
复用 vault_rag.multimodal.store 的检索逻辑（FTS trigram + CJK 2-gram 兜底）。
"""
from pathlib import Path

SERVER = Path.home() / ".claude" / "mcp_servers" / "rag-obsidian" / "server.py"
REPO = Path(__file__).resolve().parent.parent
MARKER = "vault-rag multimodal tool"
TOOL = '''

# == __MARKER__ (auto-injected, idempotent) ============================
try:
    import sys as _sys_mm
    _sys_mm.path.insert(0, r"__REPO__")
    from vault_rag.multimodal import store as _mm_store

    @mcp.tool()
    def multimodal_search(query: str, top_k: int = 5) -> dict:
        """检索已处理的 PDF/PPTX 多模态页（云端页描述/文字层/复盘摘要）。

        命中带页码与原文件绝对路径；描述是中文要点，适合回答"这份资料讲了什么"。

        Args:
            query: 自然语言问题（口语化长句也可以）。
            top_k: 返回页数上限。
        """
        hits = _mm_store.search(query_text=query, top_k=max(1, min(20, top_k)))
        out = []
        for h in hits:
            out.append({"file": Path(h["src"]).name, "src": h["src"],
                        "page": h["page"], "kind": h["kind"],
                        "score": h["score"], "text": (h["text"] or "")[:300]})
        return {"query": query, "hits": out}
except Exception:
    import traceback as _tb
    _tb.print_exc()
'''
TOOL = TOOL.replace("__MARKER__", MARKER).replace("__REPO__", REPO.as_posix())

src = SERVER.read_text(encoding="utf-8")
if MARKER in src:
    print("already injected")
else:
    lines = src.splitlines()
    gi = next((i for i, l in enumerate(lines)
               if l.strip().startswith('if __name__')), len(lines))
    SERVER.with_suffix(".py.bak_pre(mm)").write_text(src, encoding="utf-8")
    fixed = "
".join(lines[:gi] + TOOL.splitlines() + lines[gi:]) + "
"
    Path(str(SERVER)).write_text(fixed, encoding="utf-8")
    print("injected OK ->", SERVER)
