# -*- coding: utf-8 -*-
"""检索器：查询 → Qwen3 官方 last-token pooling → L2 归一化 → numpy 余弦 top-k。

与 indexer_qwen.py 的编码方式完全同步（last_token_pool + normalize + instruction 前缀）。
用法：
    python search.py "查询词"            # 命令行检索
    from search import search           # 供 MCP/脚本调用

实现要点：
- 文本与向量在一条 SQL 里 JOIN 取出，chunk_id 是否连续无关紧要（修复删除后错配）
- 向量矩阵进程内缓存（库文件 mtime 变化自动失效），MCP 连续查询免重复扫库
- 模型懒加载：import 不触发 torch，测试与纯 SQL 工具零模型依赖
"""
from __future__ import annotations

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import sqlite3
import sys

import numpy as np

from config import DB_PATH, MODEL_NAME_QWEN, DIM, TOP_K, QUERY_INSTRUCTION

MAX_LEN = 512
EXCLUDE_PATTERNS = ["%.codex/%"]   # 排除系统目录

# 缓存上限（字节），超过则退化为每次现读。可用 RAG_VEC_CACHE_MB 调整（0=禁用）。
_CACHE_MAX_BYTES = int(os.environ.get("RAG_VEC_CACHE_MB", "2048")) * 1024 * 1024
_CACHE: dict = {"stamp": None}

_MODEL = None
_TOKENIZER = None


def load_model():
    """加载查询侧模型（进程内只加载一次；import 本模块不触发）。"""
    global _MODEL, _TOKENIZER
    if _MODEL is not None:
        return _MODEL, _TOKENIZER
    import torch
    from transformers import AutoModel, AutoTokenizer
    print("加载 Qwen3-Embedding-0.6B (查询侧)...", flush=True)
    model = AutoModel.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True).float().eval()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    torch.set_num_threads(min(10, os.cpu_count()))
    _MODEL, _TOKENIZER = model, tokenizer
    return model, tokenizer


def _last_token_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    seq_len = attention_mask.sum(dim=1) - 1
    idx = seq_len.view(-1, 1, 1).expand(-1, 1, last_hidden.size(-1))
    return last_hidden.gather(1, idx).squeeze(1)


def embed_query(query: str) -> np.ndarray:
    """查询侧：instruction 前缀 + last-token pooling + L2 归一化（与索引器一致）。"""
    import torch
    model, tok = load_model()
    text = QUERY_INSTRUCTION + query
    with torch.no_grad():
        inputs = tok([text], return_tensors="pt", padding=True,
                     truncation=True, max_length=MAX_LEN)
        outputs = model(**inputs)
        emb = _last_token_pool(outputs.last_hidden_state, inputs["attention_mask"])
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        return emb.numpy().astype(np.float32)[0]


def _db_stamp() -> tuple:
    try:
        st = os.stat(DB_PATH)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _sql_where(scope_dir: str | None) -> tuple[str, list]:
    where, params = "", []
    for pat in EXCLUDE_PATTERNS:
        where += " AND c.rel_path NOT LIKE ? "
        params.append(pat)
    if scope_dir:
        where += " AND c.rel_path LIKE ? "
        params.append(scope_dir + "%")
    return where, params


def fetch_rows(scope_dir: str | None = None) -> list[tuple]:
    """一次 JOIN 取出 (chunk_id, rel_path, section, text, vec_bytes)。

    文本与向量物理同行返回，天然对齐，不依赖 chunk_id 连续。
    """
    where, params = _sql_where(scope_dir)
    con = sqlite3.connect(DB_PATH)
    try:
        return con.execute(
            "SELECT c.chunk_id, c.rel_path, c.section, c.text, b.vec "
            "FROM chunks c JOIN blob_vectors b ON b.chunk_id = c.chunk_id "
            f"WHERE 1=1{where} ORDER BY c.chunk_id", params).fetchall()
    finally:
        con.close()


def _load_matrix() -> tuple[list, list, list, np.ndarray] | None:
    """全库矩阵（进程内缓存，库变化自动失效）：(rel_paths, sections, texts, vecs)。"""
    stamp = _db_stamp()
    if stamp is None:
        return None
    cacheable = _CACHE_MAX_BYTES > 0
    if cacheable and _CACHE.get("stamp") == stamp:
        return _CACHE["data"]

    rows = fetch_rows()
    if not rows:
        return None
    rels = [r[1] for r in rows]
    secs = [r[2] for r in rows]
    texts = [r[3] for r in rows]
    vecs = np.vstack([np.frombuffer(r[4], dtype=np.float32) for r in rows])
    data = (rels, secs, texts, vecs)
    if cacheable and vecs.nbytes <= _CACHE_MAX_BYTES:
        _CACHE["stamp"] = stamp
        _CACHE["data"] = data
    return data


def search(query: str, top_k: int = TOP_K, scope_dir: str | None = None,
           min_score: float = 0.0) -> list[dict]:
    """语义检索。scope_dir 传相对目录前缀（如 '知识/'）过滤范围。"""
    data = _load_matrix()
    if data is None:
        return []
    rels, secs, texts, vecs = data
    if scope_dir:
        idx_arr = np.array([i for i, rp in enumerate(rels) if rp.startswith(scope_dir)],
                           dtype=np.int64)
        if idx_arr.size == 0:
            return []
        sub = vecs[idx_arr]
        rels_s = [rels[i] for i in idx_arr]
        secs_s = [secs[i] for i in idx_arr]
        texts_s = [texts[i] for i in idx_arr]
    else:
        sub, rels_s, secs_s, texts_s = vecs, rels, secs, texts

    qv = embed_query(query)
    sims = sub @ qv                       # 向量已归一化，点积即余弦
    n = sims.shape[0]

    k = min(n, top_k * 8)
    order = np.argpartition(-sims, k - 1)[:k] if k < n else np.arange(n)
    order = order[np.argsort(-sims[order])]          # 候选内按分数降序
    out, seen_notes = [], set()
    for i in order:
        i = int(i)
        if rels_s[i] in seen_notes:       # 同一篇笔记只留最高分的一块
            continue
        seen_notes.add(rels_s[i])
        out.append({"score": float(sims[i]), "rel_path": rels_s[i],
                    "section": secs_s[i], "text": texts_s[i]})
        if len(out) >= top_k:
            break
    if len(out) < top_k and k < n:        # 候选被同笔记去重耗尽 → 全量兜底
        full = np.argsort(-sims)
        for i in full:
            i = int(i)
            if rels_s[i] in seen_notes:
                continue
            seen_notes.add(rels_s[i])
            out.append({"score": float(sims[i]), "rel_path": rels_s[i],
                        "section": secs_s[i], "text": texts_s[i]})
            if len(out) >= top_k:
                break
    if min_score > 0:
        out = [x for x in out if x["score"] >= min_score]
    return out


def fmt(results: list[dict]) -> str:
    lines = []
    for i, r in enumerate(results, 1):
        snippet = r["text"].replace("\n", " ")[:160]
        lines.append(f"{i}. [{r['score']:.4f}] {r['rel_path']} :: {r['section'] or '-'}\n"
                     f"   {snippet}")
    return "\n".join(lines)


if __name__ == "__main__":
    query = sys.argv[1] if len(sys.argv) > 1 else ""
    scope = sys.argv[2] if len(sys.argv) > 2 else None
    if not query:
        print("用法: python search.py <查询> [范围目录]")
        sys.exit(1)
    results = search(query, scope_dir=scope)
    if not results:
        print("(无结果——索引可能还在构建中)")
    else:
        print(fmt(results))
