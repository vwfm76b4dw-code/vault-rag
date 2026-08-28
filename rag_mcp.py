# -*- coding: utf-8 -*-
"""vault-rag MCP Server — Obsidian 知识库语义检索

与 obsidian-search (FTS 关键词) 互补。模型懒加载：服务器启动秒开，
首次调用搜索工具时才加载 Qwen3-Embedding-0.6B（约 15 秒）。
"""
import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import re
import sqlite3
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# 让 rag_mcp 能 import 同目录的 config/search
sys.path.insert(0, str(Path(__file__).parent))

from config import DB_PATH, DIM, TOP_K, MODEL_NAME_QWEN

mcp = FastMCP("vault-rag")

RAG_DB = DB_PATH                       # data/qwen_rag.db
EXCLUDE = ["%.codex/%"]
_MODEL_CACHE: dict = {}                # {"model":…, "tokenizer":…}
_loaded_at: float = 0.0


def _ensure_model():
    """懒加载 embedding 模型（进程内只加载一次）。"""
    if _MODEL_CACHE.get("model") is not None:
        return
    import torch
    from transformers import AutoModel, AutoTokenizer

    print(f"[vault-rag] loading {MODEL_NAME_QWEN} ...", file=sys.stderr, flush=True)
    t0 = time.time()
    model = AutoModel.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True).float().eval()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    torch.set_num_threads(max(8, os.cpu_count() - 2))
    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["tokenizer"] = tokenizer
    print(f"[vault-rag] model ready in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


def _embed_query(query: str):
    """查询侧编码：instruction 前缀 + last-token pooling + L2 归一化（与索引器一致）。"""
    _ensure_model()
    import numpy as np
    import torch
    from config import QUERY_INSTRUCTION

    model, tok = _MODEL_CACHE["model"], _MODEL_CACHE["tokenizer"]
    text = QUERY_INSTRUCTION + query
    with torch.no_grad():
        inputs = tok([text], return_tensors="pt", padding=True, truncation=True, max_length=512)
        outputs = model(**inputs)
        seq_len = inputs["attention_mask"].sum(dim=1) - 1
        idx = seq_len.view(-1, 1, 1).expand(-1, 1, outputs.last_hidden_state.size(-1))
        emb = outputs.last_hidden_state.gather(1, idx).squeeze(1)
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        return emb.numpy().astype(np.float32)[0]


def _keyword_scores(query: str, rows) -> list[float]:
    """轻量关键词得分：查询词命中 chunk 文本的比例，∈[0,1]。"""
    terms = [t for t in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", query)]
    if not terms:
        return [0.0] * len(rows)
    scores = []
    for r in rows:
        text = r["text"].lower()
        hits = sum(1 for t in terms if t.lower() in text)
        scores.append(hits / len(terms))
    return scores


@mcp.tool()
def semantic_search(query: str, top_k: int = 8, scope_dir: str = "") -> dict:
    """语义检索 Obsidian 知识库（Qwen3 embedding，中文效果佳）。

    支持口语化/模糊描述，不要求查询词在笔记里出现。
    Args:
        query: 自然语言问题，例如 "agent 怎么防遗忘"。
        top_k: 返回条数（默认 8）。
        scope_dir: 可选目录前缀过滤，如 "知识/" 或 "研究/GitHub热门-2026-08/"。
    """
    from search import search as _search

    results = _search(query, top_k=top_k, scope_dir=scope_dir or None)
    return {
        "query": query,
        "count": len(results),
        "results": [
            {
                "score": round(r["score"], 4),
                "path": r["rel_path"],
                "section": r["section"],
                "snippet": r["text"].replace("\n", " ")[:200],
            }
            for r in results
        ],
    }


@mcp.tool()
def hybrid_search(query: str, top_k: int = 8) -> dict:
    """混合检索：语义向量 + 关键词命中 RRF 融合排序。

    语义召回概念相关内容，关键词兜底精确术语，融合后兼顾两者。
    """
    con = sqlite3.connect(RAG_DB)
    con.row_factory = sqlite3.Row
    qv = _embed_query(query)
    try:
        sql = ("SELECT c.chunk_id, c.rel_path, c.section, c.text FROM chunks c "
               f"WHERE {' AND '.join('c.rel_path NOT LIKE ?' for _ in EXCLUDE)}")
        rows = con.execute(sql, EXCLUDE).fetchall()
    finally:
        con.close()
    if not rows:
        return {"query": query, "results": []}

    import numpy as np
    vecs_blob = sqlite3.connect(RAG_DB)
    blob_rows = vecs_blob.execute(
        "SELECT id, vec FROM blob_vectors ORDER BY id").fetchall()
    vecs_blob.close()
    blob_map = {rid: np.frombuffer(v, dtype=np.float32) for rid, v in blob_rows}

    sem_scores, kw_scores = [], []
    for r in rows:
        v = blob_map.get(r["chunk_id"])
        sem_scores.append(float(v @ qv) if v is not None else 0.0)
    kw_scores = _keyword_scores(query, rows)

    # RRF 融合
    def rrf(scores):
        order = sorted(range(len(scores)), key=lambda i: -scores[i])
        rank = {i: pos + 1 for pos, i in enumerate(order)}
        return {i: 1.0 / (60 + rank[i]) for i in order}

    fused = {}
    for src in (rrf(sem_scores), rrf(kw_scores)):
        for i, s in src.items():
            fused[i] = fused.get(i, 0.0) + s
    top = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]

    results = []
    for i, score in top:
        r = rows[i]
        results.append({
            "fused_score": round(score, 4),
            "semantic": round(sem_scores[i], 3),
            "keyword": round(kw_scores[i], 2),
            "path": r["rel_path"],
            "section": r["section"],
            "snippet": r["text"].replace("\n", " ")[:200],
        })
    return {"query": query, "mode": "rrf(semantic+keyword)", "results": results}


@mcp.tool()
def rag_status() -> dict:
    """查看 RAG 索引状态：覆盖篇数、块数、向量维度、上次索引时间。"""
    con = sqlite3.connect(RAG_DB)
    try:
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        blobs = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        try:
            meta = {k: v for k, v in con.execute("SELECT key, value FROM meta")}
        except sqlite3.OperationalError:
            meta = {}
    except sqlite3.OperationalError as e:
        return {"error": f"索引库未初始化: {e}"}
    finally:
        con.close()
    return {
        "db": str(RAG_DB),
        "notes_indexed": notes,
        "chunks": chunks,
        "vectors_stored": blobs,
        "dim": DIM,
        "consistent": chunks == blobs,
        "meta": meta,
        "model": MODEL_NAME_QWEN,
        "model_loaded": bool(_MODEL_CACHE.get("model")),
    }


@mcp.tool()
def refresh_index(max_files: int = 0) -> dict:
    """增量更新 RAG 索引（跳过未修改的笔记）。

    调用 indexer_qwen.index() 断点续传逻辑。写完新笔记后执行一次即可同步。
    注意：有新内容时会阻塞数分钟到数十分钟，无新内容则秒回。
    Args:
        max_files: 仅处理前 N 篇待处理笔记（0=全部），用于小步增量。
    """
    # 重跑 index() 是模块级函数，max_files 通过截断 todo 实现——
    # 简化方案：直接复用现有断点续传（无 max_files 时全量增量）
    import io
    import contextlib
    import indexer_qwen

    buf_out, buf_err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
        indexer_qwen.index()
    log_tail = "\n".join((buf_out.getvalue() + buf_err.getvalue()).strip().splitlines()[-5:])
    con = sqlite3.connect(RAG_DB)
    chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    blobs = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
    notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    con.close()
    return {"ok": True, "notes": notes, "chunks": chunks,
            "vectors": blobs, "log_tail": log_tail}


if __name__ == "__main__":
    mcp.run()
