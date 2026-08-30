# -*- coding: utf-8 -*-
"""repo_admin.py — RAG 仓库管理：笔记清单/删除/缓存清理/真空压缩/全量重建。

全部操作只碰索引产物（data/qwen_rag.db），vault 原文只读不写。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from vault_rag.config import DB_PATH, DATA_DIR


def _con(readonly: bool = False):
    if readonly:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    else:
        con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def notes_page(q: str = "", domain: str = "", page: int = 1, size: int = 30) -> dict:
    """分页列出已索引笔记（q 匹配路径，domain 顶层目录过滤）。"""
    con = _con(readonly=True)
    try:
        where, params = "WHERE 1=1", []
        if q:
            where += " AND n.rel_path LIKE ?"
            params.append(f"%{q}%")
        if domain:
            where += " AND n.rel_path LIKE ?"
            params.append(f"{domain}/%")
        total = con.execute(f"SELECT COUNT(*) FROM notes n {where}", params).fetchone()[0]
        rows = con.execute(
            f"""SELECT n.rel_path, n.n_chunks, n.mtime,
                       (SELECT COUNT(*) FROM blob_vectors b JOIN chunks c
                          ON c.chunk_id=b.chunk_id WHERE c.rel_path=n.rel_path) AS vecs
                FROM notes n {where}
                ORDER BY n.mtime DESC LIMIT ? OFFSET ?""",
            params + [size, (max(1, page) - 1) * size]).fetchall()
        domains = [r[0] for r in con.execute(
            """SELECT DISTINCT CASE WHEN instr(rel_path,'/')>0
                   THEN substr(rel_path,1,instr(rel_path,'/')-1) ELSE '(根级)' END
               FROM notes ORDER BY 1""")]
        return {
            "total": total, "page": max(1, page), "size": size,
            "pages": max(1, -(-total // size)),
            "domains": domains,
            "notes": [{"rel_path": r["rel_path"], "chunks": r["n_chunks"],
                       "vectors": r["vecs"], "mtime_str": time.strftime(
                           "%m-%d %H:%M", time.localtime(r["mtime"]))}
                      for r in rows],
        }
    finally:
        con.close()


def delete_note(rel_path: str) -> dict:
    """从索引中移除一篇笔记（块+向量+登记行）；vault 原文不动。"""
    con = _con()
    try:
        n = con.execute("SELECT COUNT(*) FROM chunks WHERE rel_path=?", (rel_path,)).fetchone()[0]
        if n == 0:
            raise ValueError(f"索引中不存在: {rel_path}")
        con.execute("DELETE FROM blob_vectors WHERE chunk_id IN "
                    "(SELECT chunk_id FROM chunks WHERE rel_path=?)", (rel_path,))
        con.execute("DELETE FROM chunks WHERE rel_path=?", (rel_path,))
        con.execute("DELETE FROM notes WHERE rel_path=?", (rel_path,))
        con.commit()
    finally:
        con.close()
    _bust_cache()
    return {"rel_path": rel_path, "chunks_removed": n}


def stats() -> dict:
    con = _con(readonly=True)
    try:
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vectors = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        cache = con.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
    finally:
        con.close()
    db_mb = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0
    return {"notes": notes, "chunks": chunks, "vectors": vectors,
            "embed_cache": cache, "db_mb": round(db_mb, 1),
            "consistent": chunks == vectors}


def clear_cache() -> dict:
    """清空 embedding KV 缓存（下次重建索引会重新编码，检索不受影响）。"""
    con = _con()
    try:
        n = con.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
        con.execute("DELETE FROM embed_cache")
        con.commit()
    finally:
        con.close()
    return {"cleared": n}


def vacuum() -> dict:
    """VACUUM 压缩数据库（删除/重建后回收空间）。"""
    before = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0
    con = sqlite3.connect(DB_PATH, timeout=30)
    try:
        con.execute("VACUUM")
    finally:
        con.close()
    after = DB_PATH.stat().st_size / 1e6 if DB_PATH.exists() else 0
    return {"before_mb": round(before, 1), "after_mb": round(after, 1)}


def rebuild_all() -> dict:
    """全量重建：清空 chunks/向量/笔记登记（保留 embed KV 缓存 → 未变内容秒级重编）。"""
    con = _con()
    try:
        for table in ("blob_vectors", "chunks", "notes"):
            con.execute(f"DELETE FROM {table}")
        con.commit()
    finally:
        con.close()
    _bust_cache()
    return {"ok": True, "message": "索引已清空（KV 缓存保留），请执行增量索引重建"}


def _bust_cache():
    """向量化缓存失效（进程内）。"""
    try:
        from vault_rag import search
        search._CACHE["stamp"] = None
    except Exception:
        pass
