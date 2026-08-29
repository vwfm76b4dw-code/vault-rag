# -*- coding: utf-8 -*-
"""向 rag-obsidian/server.py 注入 RAG 融合层（32 工具版）。
独立脚本避免 shell heredoc 的编码/转义地狱。"""
from pathlib import Path

BASE = Path.home() / ".claude" / "mcp_servers" / "rag-obsidian" / "server.py"
src = BASE.read_text(encoding="utf-8")

src = src.replace(
    '"""Obsidian Vault MCP Server — FTS5 + 正则 + 模糊 + 拓扑 + 写入 + 高级搜索"""',
    '"""RAG-Obsidian MCP Server — FTS5/正则/模糊/拓扑/写入 + 语义检索/时效裁决/知识关系图\n\n'
    '深度融合层（2026-08-28）：semantic_search / get_note_relations / note_freshness；\n'
    'embedding 经 HTTP(127.0.0.1:1234) 外置，本进程保持轻量。\n'
    '原 obsidian-search 保留为纯文本备份服务器。"""')
src = src.replace('mcp = FastMCP("obsidian-search")', 'mcp = FastMCP("rag-obsidian")')

FUSION = '''

# == RAG 深度融合层 (2026-08-28) ======================================
import urllib.request as _urlreq

_RAG_DIR = Path(r"@VAULT_RAG_ROOT@")   # 由 inject_fusion.py 注入时替换为本仓库根
_RAG_DB = _RAG_DIR / "data" / "qwen_rag.db"
_REL_DB = _RAG_DIR / "data" / "relations.db"
_EMB_URL = "http://127.0.0.1:1234/v1/embeddings"
_EMB_MODEL = "text-embedding-qwen3-embedding-0.6b"
_QUERY_INSTR = ("Instruct: 给定用户的提问，从个人 Obsidian 知识库中"
                "检索最相关的笔记片段\\nQuery: ")


def _embed_remote(texts):
    """经 LM Studio 端点编码；失败返回 None -> 调用方降级 FTS。"""
    try:
        req = _urlreq.Request(
            _EMB_URL,
            data=json.dumps({"model": _EMB_MODEL, "input": texts}).encode("utf-8"),
            headers={"Content-Type": "application/json"})
        with _urlreq.urlopen(req, timeout=60) as r:
            return [d["embedding"] for d in json.loads(r.read())["data"]]
    except Exception:
        return None


@mcp.tool()
def semantic_search(query: str, top_k: int = 8, scope_dir: str = "") -> dict:
    """语义检索 vault-rag 向量索引（Qwen3-0.6B，中文强，支持口语化模糊查询）。

    Args:
        query: 自然语言问题。
        top_k: 返回条数。
        scope_dir: 可选目录前缀过滤，如 '知识/'。
    需要 LM Studio 端点(1234)在线；离线时自动降级关键词路。
    """
    import numpy as np
    if not _RAG_DB.exists():
        return {"error": "向量库不存在，先跑 run_index.py 建索引"}
    ev = _embed_remote([_QUERY_INSTR + query])
    if not ev:
        fb = search_notes_advanced(query, mode="hybrid", limit=top_k)
        return {"degraded": "embedding 端点离线，已降级 FTS", "results": fb}
    qv = np.asarray(ev[0], dtype=np.float32)
    qv /= max(float(np.linalg.norm(qv)), 1e-9)
    con = sqlite3.connect(f"file:{_RAG_DB}?mode=ro", uri=True)
    sql = ("SELECT c.chunk_id, c.rel_path, c.section, c.text FROM chunks c "
           "JOIN blob_vectors b ON b.chunk_id=c.chunk_id "
           "WHERE c.rel_path NOT LIKE '%.codex%' ")
    params = []
    if scope_dir:
        sql += "AND c.rel_path LIKE ? "
        params.append(scope_dir + "%")
    rows = con.execute(sql, params).fetchall()
    if not rows:
        con.close()
        return {"results": []}
    ids = np.fromiter((r[0] for r in rows), dtype=np.int64)
    mat = np.vstack([np.frombuffer(con.execute(
        "SELECT vec FROM blob_vectors WHERE chunk_id=?", (int(i),)).fetchone()[0],
        dtype=np.float32) for i in ids])
    con.close()
    sims = mat @ qv
    order = np.argsort(-sims)[:top_k * 3]
    out, seen = [], set()
    for i in order:
        cid, rp, sec, txt = rows[int(i)]
        if rp in seen:
            continue
        seen.add(rp)
        out.append({"score": round(float(sims[i]), 4), "path": rp,
                    "section": sec or "", "snippet": txt.replace("\\n", " ")[:160]})
        if len(out) >= top_k:
            break
    if _REL_DB.exists():
        rel = sqlite3.connect(f"file:{_REL_DB}?mode=ro", uri=True)
        superseded = {d for (d,) in rel.execute(
            "SELECT dst FROM edges WHERE kind='supersedes'")}
        rel.close()
        for o in out:
            if o["path"] in superseded:
                o["score"] = round(o["score"] * 0.5, 4)
                o["freshness_warning"] = "该文档存在更新版本（已被裁决取代）"
        out.sort(key=lambda x: -x["score"])
    return {"count": len(out), "results": out}


@mcp.tool()
def get_note_relations(path: str) -> dict:
    """一篇笔记的知识关系图：references(wikilink)/supersedes(版本取代)/
    sibling_next(时序流)/complements(跨簇互补)。用于关联阅读与知识整理。

    Args:
        path: 相对路径，如 '知识/原理/SDD-规格驱动开发深度研究.md'
    """
    if not _REL_DB.exists():
        return {"error": "关系库未构建，先跑 relations.py build"}
    con = sqlite3.connect(f"file:{_REL_DB}?mode=ro", uri=True)
    out = {"path": path, "outgoing": [], "incoming": []}
    for dst, kind, conf, why in con.execute(
            "SELECT dst,kind,conf,why FROM edges WHERE src=? ORDER BY conf DESC",
            (path,)):
        out["outgoing"].append({"to": dst, "kind": kind,
                                "conf": round(conf, 2), "why": why})
    for s, kind, conf, why in con.execute(
            "SELECT src,kind,conf,why FROM edges WHERE dst=? ORDER BY conf DESC",
            (path,)):
        out["incoming"].append({"from": s, "kind": kind,
                                "conf": round(conf, 2), "why": why})
    con.close()
    return out


@mcp.tool()
def note_freshness(path: str) -> dict:
    """单篇文件时效诊断：所在簇、权威地位、信号明细(S1声明/S2体积/S3内嵌日期)。"""
    import sys as _sys
    if str(_RAG_DIR) not in _sys.path:
        _sys.path.insert(0, str(_RAG_DIR))
    from freshness import extract_signals, cluster_of
    p = VAULT_PATH / path
    if not p.exists():
        return {"error": f"文件不存在: {path}"}
    m = extract_signals(p, path)
    verdict = {"is_stale_source": m.is_stale_source,
               "has_history_mark": m.has_history_mark,
               "embedded_date": m.best_date, "size": m.size,
               "cluster_key": cluster_of(path)}
    if _REL_DB.exists():
        rel = sqlite3.connect(f"file:{_REL_DB}?mode=ro", uri=True)
        w = rel.execute("SELECT src FROM edges WHERE dst=? AND kind='supersedes'",
                        (path,)).fetchone()
        if w:
            verdict["superseded_by"] = w[0]
        kids = rel.execute(
            "SELECT dst FROM edges WHERE src=? AND kind IN ('sibling_next','supersedes') LIMIT 8",
            (path,)).fetchall()
        verdict["related_in_cluster"] = [k[0] for k in kids]
        rel.close()
    return verdict


'''

anchor = 'if __name__ == "__main__":'
assert anchor in src, "anchor missing"
src = src.replace(anchor, FUSION + anchor)
src = src.replace("@VAULT_RAG_ROOT@", str(Path(__file__).resolve().parent))
BASE.write_text(src, encoding="utf-8")
import ast
ast.parse(src)
print(f"injected OK, tools={src.count('@mcp.tool()')}")
