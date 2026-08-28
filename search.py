# -*- coding: utf-8 -*-
"""检索器：查询 → Qwen3 官方 last-token pooling → L2 归一化 → numpy 余弦 top-k。

与 indexer_qwen.py 的编码方式完全同步（last_token_pool + normalize + instruction 前缀）。
用法：
    python search.py "查询词"            # 命令行检索
    from search import search           # 供 MCP/脚本调用
"""
import os
os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'

import sqlite3
import sys

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from config import DB_PATH, VEC_PATH, MODEL_NAME_QWEN, DIM, TOP_K, QUERY_INSTRUCTION

MAX_LEN = 512
EXCLUDE_PATTERNS = ["%.codex/%"]   # 排除系统目录


def load_model():
    print("加载 Qwen3-Embedding-0.6B (查询侧)...", flush=True)
    model = AutoModel.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True).float().eval()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME_QWEN, trust_remote_code=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    torch.set_num_threads(min(10, os.cpu_count()))
    return model, tokenizer


_MODEL, _TOKENIZER = load_model()


def _last_token_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    seq_len = attention_mask.sum(dim=1) - 1
    idx = seq_len.view(-1, 1, 1).expand(-1, 1, last_hidden.size(-1))
    return last_hidden.gather(1, idx).squeeze(1)


def embed_query(query: str) -> np.ndarray:
    """查询侧：instruction 前缀 + last-token pooling + L2 归一化（与索引器一致）。"""
    text = QUERY_INSTRUCTION + query
    with torch.no_grad():
        inputs = _TOKENIZER([text], return_tensors="pt", padding=True,
                            truncation=True, max_length=MAX_LEN)
        outputs = _MODEL(**inputs)
        emb = _last_token_pool(outputs.last_hidden_state, inputs["attention_mask"])
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)
        return emb.numpy().astype(np.float32)[0]


def search(query: str, top_k: int = TOP_K, scope_dir: str | None = None,
           min_score: float = 0.0) -> list[dict]:
    """语义检索。scope_dir 传相对目录前缀（如 '知识/'）过滤范围。"""
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        qv = embed_query(query)
        con2 = sqlite3.connect(DB_PATH)
        rows = con2.execute(
            "SELECT b.vec FROM blob_vectors b "
            "JOIN chunks c ON c.chunk_id = b.chunk_id "
            "ORDER BY c.chunk_id").fetchall()
        con2.close()
        if not rows:
            return []
        vecs = np.vstack([np.frombuffer(r[0], dtype=np.float32).reshape(1, -1) for r in rows])
        n_rows = vecs.shape[0]
        if n_rows == 0:
            return []

        sql = ("SELECT c.chunk_id, c.rel_path, c.section, c.text FROM chunks c "
               "WHERE c.chunk_id < ? ")
        params: list = [n_rows]
        for pat in EXCLUDE_PATTERNS:
            sql += "AND c.rel_path NOT LIKE ? "
            params.append(pat)
        if scope_dir:
            sql += "AND c.rel_path LIKE ? "
            params.append(scope_dir + "%")
        rows = con.execute(sql, params).fetchall()
        if not rows:
            return []

        ids = np.fromiter((r["chunk_id"] for r in rows), dtype=np.int64)
        sub = np.asarray(vecs[ids], dtype=np.float32)
        sims = sub @ qv                       # 向量已归一化，点积即余弦
        order = np.argsort(-sims)[:top_k * 4]  # 多取一些用于去重
        out, seen_notes = [], set()
        for i in order:
            r = rows[int(i)]
            if r["rel_path"] in seen_notes:    # 同一篇笔记只留最高分的一块
                continue
            seen_notes.add(r["rel_path"])
            out.append({"score": float(sims[i]), "rel_path": r["rel_path"],
                        "section": r["section"], "text": r["text"]})
            if len(out) >= top_k:
                break
        return [x for x in out if x["score"] >= min_score] if min_score > 0 else out
    finally:
        con.close()


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
