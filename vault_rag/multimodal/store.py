# -*- coding: utf-8 -*-
"""store.py — 多模态独立索引库 data/multimodal.db。

刻意独立于主库 qwen_rag.db：向量空间不同（VL-Embedding ≠ 0.6B 文本模型），
自愈/迁移逻辑互不干扰。三类块：
  text    页文字层（FTS 可搜）
  caption 云端描述（FTS 可搜；策略平衡/高性能）
  summary 复盘综合（高性能档，page=0）
  向量列仅当该页做过本地 VL 嵌入（省钱档 / 校准后启用）
"""
from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from vault_rag.config import DATA_DIR

MM_DB = DATA_DIR / "multimodal.db"
DIM = 2048                       # Qwen3-VL-Embedding-2B 原生维（独立空间不截断）

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  src TEXT PRIMARY KEY, kind TEXT, pages INTEGER,
  strategy TEXT, mtime REAL, status TEXT);
CREATE TABLE IF NOT EXISTS mm_chunks(
  id INTEGER PRIMARY KEY,
  src TEXT NOT NULL, page INTEGER NOT NULL,
  kind TEXT NOT NULL, text TEXT, vec BLOB, model TEXT, mtime REAL);
CREATE INDEX IF NOT EXISTS mm_src_idx ON mm_chunks(src, page);
CREATE VIRTUAL TABLE IF NOT EXISTS mm_fts USING fts5(text, content='mm_chunks', content_rowid='id', tokenize='trigram');
CREATE TRIGGER IF NOT EXISTS mm_fts_ai AFTER INSERT ON mm_chunks BEGIN
  INSERT INTO mm_fts(rowid, text) VALUES (new.id, new.text); END;
CREATE TRIGGER IF NOT EXISTS mm_fts_ad AFTER DELETE ON mm_chunks BEGIN
  INSERT INTO mm_fts(mm_fts, rowid, text) VALUES ('delete', old.id, old.text); END;
CREATE TRIGGER IF NOT EXISTS mm_fts_au AFTER UPDATE ON mm_chunks BEGIN
  INSERT INTO mm_fts(mm_fts, rowid, text) VALUES ('delete', old.id, old.text);
  INSERT INTO mm_fts(rowid, text) VALUES (new.id, new.text); END;
"""


@contextmanager
def cx():
    """连接作用域：提交并关闭（sqlite3 的 with 语义不关连接，Windows 会锁文件）。"""
    c = con()
    try:
        yield c
        c.commit()
    finally:
        c.close()


def con() -> sqlite3.Connection:
    MM_DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(MM_DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript(_SCHEMA)
    return c


def source_current(src: str, mtime: float) -> bool:
    """该来源已按当前 mtime 处理过（增量幂等）。"""
    with cx() as c:
        row = c.execute("SELECT mtime, status FROM sources WHERE src=?",
                        (src,)).fetchone()
    return bool(row and row["status"] == "ok" and abs(row["mtime"] - mtime) < 1)


def register_source(src: str, kind: str, pages: int, strategy: str,
                    status: str = "ok") -> None:
    with cx() as c:
        c.execute("INSERT INTO sources VALUES(?,?,?,?,?,?) "
                  "ON CONFLICT(src) DO UPDATE SET kind=?, pages=?, strategy=?, "
                  "mtime=?, status=?",
                  (src, kind, pages, strategy, time.time(), status,
                   kind, pages, strategy, time.time(), status))
        c.commit()


def delete_source(src: str) -> int:
    with cx() as c:
        n = c.execute("DELETE FROM mm_chunks WHERE src=?", (src,)).rowcount
        c.execute("DELETE FROM sources WHERE src=?", (src,))
        c.commit()
    return n


def add_chunk(src: str, page: int, kind: str, text: str,
              vec=None, model: str = "") -> int:
    with cx() as c:
        cur = c.execute(
            "INSERT INTO mm_chunks(src,page,kind,text,vec,model,mtime) "
            "VALUES(?,?,?,?,?,?,?)",
            (src, page, kind, text,
             None if vec is None else vec.astype("float32").tobytes(),
             model, time.time()))
        c.commit()
        return cur.lastrowid


def stats() -> dict:
    with cx() as c:
        n = c.execute("SELECT COUNT(*) FROM mm_chunks").fetchone()[0]
        s = c.execute("SELECT COUNT(*) FROM sources").fetchone()[0]
        v = c.execute("SELECT COUNT(*) FROM mm_chunks WHERE vec IS NOT NULL").fetchone()[0]
    return {"chunks": n, "sources": s, "vectors": v}


def search(query_vec=None, query_text: str = "", top_k: int = 6) -> list[dict]:
    """向量 + FTS 双路召回，各自归一后合并（同一块取最高分）。

    归一化是必须的：FTS bm25 分与余弦相似度量纲不同，
    不归一会导致一条路永远压死另一条（实测笔记 FTS 0.8 vs 照片余弦 0.5）。
    """
    vec_hits: list[tuple[float, object]] = []
    if query_vec is not None:
        with cx() as c:
            rows = c.execute(
                "SELECT id,src,page,kind,text,vec FROM mm_chunks "
                "WHERE vec IS NOT NULL").fetchall()
        import numpy as np
        q = query_vec.astype("float32")
        q /= max(float(np.linalg.norm(q)), 1e-9)
        for r in rows:
            v = np.frombuffer(r["vec"], dtype="float32")
            sim = float(q @ (v / max(float(np.linalg.norm(v)), 1e-9)))
            vec_hits.append((sim, r))
    fts_hits: list[tuple[float, object]] = []
    if query_text.strip():
        q = query_text.strip()
        terms = [t for t in q.split() if len(t) >= 3] or [q]   # trigram 需 ≥3 字
        ftsq = " OR ".join(f'"{t}"' for t in terms)
        with cx() as c:
            try:
                rows = c.execute(
                    "SELECT m.id, m.src, m.page, m.kind, m.text, "
                    "bm25(mm_fts) AS rank FROM mm_fts f JOIN mm_chunks m "
                    "ON m.id=f.rowid WHERE mm_fts MATCH ? ORDER BY rank LIMIT ?",
                    (ftsq, top_k * 4)).fetchall()
            except sqlite3.OperationalError:
                rows = []
            if not rows and len(terms) == 1 and len(terms[0]) > 6:
                # 长整句查询：滑 4 字窗取 grams OR 匹配（口语化问题常见）
                s = terms[0]
                grams = [s[i:i + 4] for i in range(0, min(len(s) - 3, 32), 3)][:8]
                ftsq2 = " OR ".join(f'"{g}"' for g in grams)
                try:
                    rows = c.execute(
                        "SELECT m.id, m.src, m.page, m.kind, m.text, "
                        "bm25(mm_fts) AS rank FROM mm_fts f JOIN mm_chunks m "
                        "ON m.id=f.rowid WHERE mm_fts MATCH ? ORDER BY rank LIMIT ?",
                        (ftsq2, top_k * 4)).fetchall()
                except sqlite3.OperationalError:
                    rows = []
            if not rows:      # 兜底：CJK 2-gram 命中计数（口语化查询措辞不匹配时）
                import re as _re
                runs = _re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", q)
                bigrams = set()
                for run in runs:
                    if run[0].isascii():
                        bigrams.add(run.lower())
                    else:
                        bigrams |= {run[i:i + 2] for i in range(len(run) - 1)}
                if bigrams:
                    allr = c.execute(
                        "SELECT id, src, page, kind, text FROM mm_chunks"
                    ).fetchall()
                    scored = []
                    for r in allr:
                        t = (r["text"] or "").lower()
                        n = sum(1 for b in bigrams if b in t)
                        if n:
                            scored.append((n / len(bigrams), r))
                    scored.sort(key=lambda x: -x[0])
                    for s, r in scored[:top_k * 4]:
                        fts_hits.append((s, r))
            else:
                for r in rows:
                    # FTS5 bm25 返回 ≤0 的负分（越负越相关）
                    fts_hits.append((float(r["rank"]), r))

    # RRF（倒数排名融合）：双路都上榜的块自然胜出，
    # 天然消除"两路各自归一的 1.0 并列顶掉正主"的问题
    K = 60
    rrf: dict[int, float] = {}
    meta: dict[int, dict] = {}

    def _rrf_merge(pairs, how):
        for i, (_s, r) in enumerate(pairs):
            rid = r["id"]
            rrf[rid] = rrf.get(rid, 0.0) + 1.0 / (K + i + 1)
            if rid not in meta:
                meta[rid] = {"id": rid, "src": r["src"], "page": r["page"],
                             "kind": r["kind"],
                             "text": (r["text"] or "")[:300],
                             "via": how, "paths": [how]}
            elif how not in meta[rid]["paths"]:
                meta[rid]["paths"].append(how)

    _rrf_merge(vec_hits, "image")
    _rrf_merge(fts_hits, "fts")
    ranked = sorted(meta.values(), key=lambda x: -rrf[x["id"]])
    # 归一到 0~1（单路第 1 名 ≈0.5、双路第 1 名 =1.0），分数可读可比较
    scale = 1.0 / (K + 1)
    for row in ranked:
        row["score"] = round(min(1.0, rrf[row["id"]] / scale / 2), 4)
    return ranked[:top_k]


def get_chunk(chunk_id: int) -> dict | None:
    with cx() as c:
        r = c.execute("SELECT * FROM mm_chunks WHERE id=?", (chunk_id,)).fetchone()
    return dict(r) if r else None
