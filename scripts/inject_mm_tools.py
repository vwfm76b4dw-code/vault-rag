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

MARKER2 = "vault-rag semantic unification"
TOOL2 = """

# == __MARKER2__ (auto-injected, idempotent) ============================
# 注入版 standalone semantic_search 缺少仓库 search.py 的能力
# （文件名置顶 / hybrid RRF / FTS 兜底链）——统一替换为仓库实现（单一事实来源）。
try:
    from vault_rag.search import search as _vrs_search

    def _semantic_search_unified(query: str, top_k: int = 8, scope_dir: str = "") -> dict:
        hits = _vrs_search(query, top_k=max(1, min(20, top_k)),
                           scope_dir=scope_dir or None)
        results = []
        for h in hits:
            results.append({"score": round(h["score"], 4), "path": h["rel_path"],
                            "section": h.get("section") or "",
                            "snippet": (h["text"] or "").replace("\\n", " ")[:200]})
        return {"query": query, "count": len(results), "results": results}

    _t_ss = mcp._tool_manager._tools.get("semantic_search")
    if _t_ss is not None and getattr(_t_ss.fn, "__module__", "") != "vault_rag.search":
        _t_ss.fn = _semantic_search_unified
except Exception:
    import traceback as _tb2
    _tb2.print_exc()
"""
TOOL2 = TOOL2.replace("__MARKER2__", MARKER2).replace("__REPO__", REPO.as_posix())

src = SERVER.read_text(encoding="utf-8")
pending: list[str] = []
if MARKER2 not in src:
    pending.append(TOOL2)
if MARKER not in src:
    pending.append(TOOL)
if not pending:
    print("nothing to do（两块均已在）")
else:
    lines = src.splitlines()
    gi = next((i for i, l in enumerate(lines)
               if l.strip().startswith("if __name__")), len(lines))
    # 必须插在 mcp.run() 守卫之前（stdio 服务下尾部代码永不执行）
    new_lines = lines[:gi]
    for block in pending:
        new_lines += block.splitlines()
    new_lines += lines[gi:]
    SERVER.with_suffix(".py.bak_pre(mm)").write_text(src, encoding="utf-8")
    Path(str(SERVER)).write_text("\n".join(new_lines) + "\n", encoding="utf-8")
    print(f"injected {len(pending)} block(s) ->", SERVER)
