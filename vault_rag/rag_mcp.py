# -*- coding: utf-8 -*-
"""vault-rag MCP Server — Obsidian 知识库语义检索

模型懒加载：服务器启动秒开，首次调用搜索工具时才加载 Qwen3-Embedding-0.6B（约 15 秒）。
向量矩阵由 search.py 统一缓存（库文件变化自动失效），semantic/hybrid 共享。
"""
from __future__ import annotations

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import re
import sqlite3
import sys
import time
from pathlib import Path

from mcp.server.fastmcp import FastMCP

# 让 rag_mcp 能 import 同目录的 config/search
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from vault_rag.config import DB_PATH, DIM, MODEL_NAME_QWEN, TORCH_THREADS

# 预导入 numpy：stdio MCP 子进程里延迟导入扩展模块可能永久阻塞
# （Windows 管道句柄 + 扩展 DLL 初始化竞态），启动期一次性完成最稳。
import numpy  # noqa: F401

mcp = FastMCP("vault-rag")

RAG_DB = DB_PATH                       # data/qwen_rag.db
EXCLUDE = ["%.codex/%"]
_MODEL_CACHE: dict = {}                # {"model":…, "tokenizer":…}


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
    torch.set_num_threads(TORCH_THREADS)
    _MODEL_CACHE["model"] = model
    _MODEL_CACHE["tokenizer"] = tokenizer
    print(f"[vault-rag] model ready in {time.time()-t0:.0f}s", file=sys.stderr, flush=True)


def _embed_query(query: str):
    """查询侧编码：instruction 前缀 + last-token pooling + L2 归一化（与索引器一致）。"""
    _ensure_model()
    import numpy as np
    import torch
    from vault_rag.config import QUERY_INSTRUCTION

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


def _keyword_scores(query: str, texts: list[str]) -> list[float]:
    """轻量关键词得分：查询词命中 chunk 文本的比例，∈[0,1]。"""
    terms = [t for t in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", query)]
    if not terms:
        return [0.0] * len(texts)
    scores = []
    for text in texts:
        t = text.lower()
        hits = sum(1 for term in terms if term.lower() in t)
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
    from vault_rag.search import search as _search

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
    import numpy as np
    from vault_rag.search import fetch_rows

    rows = fetch_rows()          # (chunk_id, rel_path, section, text, vec_bytes) 同行对齐
    if not rows:
        return {"query": query, "results": []}
    qv = _embed_query(query)
    vecs = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])

    sem_scores = vecs @ qv
    kw_scores = np.asarray(_keyword_scores(query, [r[3] for r in rows]), dtype=np.float64)

    # RRF 融合
    def rrf(scores: np.ndarray) -> dict[int, float]:
        order = np.argsort(-scores)
        return {int(i): 1.0 / (60 + pos + 1) for pos, i in enumerate(order)}

    fused: dict[int, float] = {}
    for src in (rrf(sem_scores), rrf(kw_scores)):
        for i, s in src.items():
            fused[i] = fused.get(i, 0.0) + s
    top = sorted(fused.items(), key=lambda kv: -kv[1])[:top_k]

    results = []
    for i, score in top:
        cid, rel, sec, txt, _vec = rows[i]
        results.append({
            "fused_score": round(score, 4),
            "semantic": round(float(sem_scores[i]), 3),
            "keyword": round(float(kw_scores[i]), 2),
            "path": rel,
            "section": sec or "",
            "snippet": txt.replace("\n", " ")[:200],
        })
    return {"query": query, "mode": "rrf(semantic+keyword)", "results": results}


@mcp.tool()
def multimodal_search(query: str, top_k: int = 5) -> dict:
    """检索 PDF/PPTX 多模态页（云端页描述/文字层/复盘摘要），命中带页码与原文件路径。

    Args:
        query: 自然语言问题（口语化长句也可以）。
        top_k: 返回页数上限。
    """
    from vault_rag.multimodal import store
    hits = store.search(query_text=query, top_k=max(1, min(20, top_k)))
    return {"query": query, "hits": [
        {"file": Path(h["src"]).name, "src": h["src"], "page": h["page"],
         "kind": h["kind"], "score": h["score"], "text": (h["text"] or "")[:300]}
        for h in hits]}


@mcp.tool()
def rag_status() -> dict:
    """查看 RAG 索引状态：覆盖篇数、块数、向量维度、上次索引时间。"""
    con = sqlite3.connect(RAG_DB)
    try:
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        blobs = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        cache = con.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
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
        "embed_cache": cache,
        "dim": DIM,
        "consistent": chunks == blobs,
        "meta": meta,
        "model": MODEL_NAME_QWEN,
        "model_loaded": bool(_MODEL_CACHE.get("model")),
    }


@mcp.tool()
def refresh_index(max_files: int = 0) -> dict:
    """增量更新 RAG 索引（跳过未修改的笔记）。

    写完新笔记后执行一次即可同步。无新内容秒回；有新内容时按篇数耗时。
    Args:
        max_files: 仅处理前 N 篇待处理笔记（0=全部），用于小步增量。
    """
    import contextlib
    import io
    from vault_rag import indexer_qwen

    buf_out, buf_err = io.StringIO(), io.StringIO()
    try:
        with contextlib.redirect_stdout(buf_out), contextlib.redirect_stderr(buf_err):
            indexer_qwen.index(max_files=max_files)
    except Exception as e:                       # 索引失败也要把现场带回给调用方
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "log_tail": "\n".join((buf_out.getvalue() + buf_err.getvalue())
                                      .strip().splitlines()[-5:])}
    log_tail = "\n".join((buf_out.getvalue() + buf_err.getvalue()).strip().splitlines()[-5:])
    con = sqlite3.connect(RAG_DB)
    chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    blobs = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
    notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
    con.close()
    # 索引刚变过，清掉进程内向量缓存让下次查询重新加载
    from vault_rag import search
    search._CACHE["stamp"] = None
    return {"ok": True, "notes": notes, "chunks": chunks,
            "vectors": blobs, "log_tail": log_tail}


if __name__ == "__main__":
    mcp.run()
