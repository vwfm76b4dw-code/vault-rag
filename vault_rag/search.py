# -*- coding: utf-8 -*-
"""检索器：查询 → Qwen3 官方 last-token pooling → L2 归一化 → numpy 余弦 top-k。

与 indexer_qwen.py 的编码方式完全同步（last_token_pool + normalize + instruction 前缀）。
用法：
    python search.py "查询词"            # 命令行检索
    from vault_rag.search import search           # 供 MCP/脚本调用

实现要点：
- 文本与向量在一条 SQL 里 JOIN 取出，chunk_id 是否连续无关紧要（修复删除后错配）
- 向量矩阵进程内缓存（库文件 mtime 变化自动失效），MCP 连续查询免重复扫库
- 模型懒加载：import 不触发 torch，测试与纯 SQL 工具零模型依赖
"""
from __future__ import annotations

import os
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

import re
import sqlite3
import sys
import time

import numpy as np

from vault_rag.config import DB_PATH, MODEL_NAME_QWEN, DIM, TOP_K, QUERY_INSTRUCTION, TORCH_THREADS
from vault_rag.config import API_URL as EMBED_HTTP_URL, MODEL as EMBED_HTTP_MODEL

MAX_LEN = 512
EXCLUDE_PATTERNS = ["%.codex/%"]   # 排除系统目录

# 检索模式:'hybrid'=语义+关键词 RRF 融合(默认,精确名/术语查询精度高)
#          'semantic'=纯语义;'keyword'=纯关键词
SEARCH_MODE = os.environ.get("RAG_SEARCH_MODE", "semantic")

# 查询向量来源链（设置面板可选）：'auto'=HTTP端点→内置llama.cpp（默认）
#   'http'=仅HTTP端点；'llamacpp'=仅内置llama.cpp；'off'=纯关键词；'local'=本地torch
EMBED_BACKEND = os.environ.get("RAG_EMBED_BACKEND", "auto")
EMBED_HTTP_TIMEOUT = float(os.environ.get("RAG_EMBED_HTTP_TIMEOUT", "5"))

# 缓存上限（字节），超过则退化为每次现读。可用 RAG_VEC_CACHE_MB 调整（0=禁用）。
_CACHE_MAX_BYTES = int(os.environ.get("RAG_VEC_CACHE_MB", "2048")) * 1024 * 1024
_CACHE: dict = {"stamp": None}
_all_ids_cache: list = []   # 当前矩阵对应的 chunk_id(供关键词候选映射)

_MODEL = None
_TOKENIZER = None


class EmbedUnavailable(Exception):
    """查询向量不可得（HTTP 端点离线且未启用本地回退）→ 调用方走关键词检索。"""


_EMBED_PROBE: dict = {"t": 0.0, "ok": False}


def embed_endpoint_alive(force: bool = False) -> bool:
    """端点活性探测（缓存 8 秒）：离线期间检索零网络调用、零等待。"""
    if not force and time.time() - _EMBED_PROBE["t"] < 8:
        return _EMBED_PROBE["ok"]
    import requests
    try:
        r = requests.post(EMBED_HTTP_URL, json={"model": EMBED_HTTP_MODEL, "input": ["alive"]},
                          timeout=(1.5, 2.5))
        ok = r.status_code == 200
    except Exception:
        ok = False
    _EMBED_PROBE.update({"t": time.time(), "ok": ok})
    return ok


def embed_query_http(query: str) -> np.ndarray:
    """经 OpenAI 兼容端点取查询向量（LM Studio / llama-server / 云端 embedding）。

    档案带 key（如硅基流动）时自动带 Bearer；同模型同指令前缀，与库内向量兼容。
    """
    import requests
    headers = {}
    try:
        from vault_rag import webui_lib
        e = webui_lib.load_local_settings().get("embed") or {}
        act = next((p for p in (e.get("http_profiles") or [])
                    if p.get("name") == e.get("http_active")), None)
        if act and act.get("key"):
            headers["Authorization"] = f"Bearer {act['key']}"
    except Exception:
        pass
    r = requests.post(
        EMBED_HTTP_URL, headers=headers,
        json={"model": EMBED_HTTP_MODEL, "input": [QUERY_INSTRUCTION + query]},
        timeout=(2, EMBED_HTTP_TIMEOUT))
    r.raise_for_status()
    v = np.asarray(r.json()["data"][0]["embedding"], dtype=np.float32)
    return v / max(float(np.linalg.norm(v)), 1e-9)


def load_model():
    """加载本地查询模型（仅 RAG_EMBED_BACKEND=local/auto 或索引器使用；import 不触发）。"""
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
    torch.set_num_threads(min(TORCH_THREADS, os.cpu_count() or TORCH_THREADS))
    _MODEL, _TOKENIZER = model, tokenizer
    return model, tokenizer


def _last_token_pool(last_hidden, attention_mask):
    seq_len = attention_mask.sum(dim=1) - 1
    idx = seq_len.view(-1, 1, 1).expand(-1, 1, last_hidden.size(-1))
    return last_hidden.gather(1, idx).squeeze(1)


def embed_query_local(query: str) -> np.ndarray:
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


def embed_query(query: str) -> np.ndarray:
    """查询向量链（设置面板可选）：HTTP 端点 → 内置 llama.cpp → 无可用源时抛。

    端点确认离线时零调用零等待；本地 torch 仅 RAG_EMBED_BACKEND=local 时使用。
    """
    if EMBED_BACKEND == "local":
        return embed_query_local(query)
    if EMBED_BACKEND in ("auto", "http") and embed_endpoint_alive():
        try:
            return embed_query_http(query)
        except Exception as e:
            _EMBED_PROBE.update({"t": time.time(), "ok": False})
            if EMBED_BACKEND == "http":
                raise EmbedUnavailable(f"embedding 端点调用失败（{type(e).__name__}）") from e
    if EMBED_BACKEND in ("auto", "llamacpp"):
        try:
            from vault_rag import embed_providers
            return np.asarray(
                embed_providers.embed_llamacpp(QUERY_INSTRUCTION + query),
                dtype=np.float32)
        except Exception as e:
            if EMBED_BACKEND == "llamacpp":
                raise EmbedUnavailable(f"内置 llama.cpp 失败: {e}") from e
    raise EmbedUnavailable("无可用向量源（端点离线且未配置 llama.cpp）")


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
    global _all_ids_cache
    _all_ids_cache = [r[0] for r in rows]
    data = (rels, secs, texts, vecs)
    if cacheable and vecs.nbytes <= _CACHE_MAX_BYTES:
        _CACHE["stamp"] = stamp
        _CACHE["data"] = data
    return data


def _terms(query: str) -> list[str]:
    """查询切分:英文整词;中文长串切 2-gram(整句精确匹配基本命不中)。"""
    toks = []
    for run in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", query):
        if run[0].isascii():
            toks.append(run.lower())
        elif len(run) <= 2:
            toks.append(run)
        else:
            toks += [run[i:i + 2] for i in range(len(run) - 1)]
    return toks


def _kw_scores(terms: list[str], rels_s: list[str],
               cid_to_idx: dict[int, int]) -> np.ndarray:
    """关键词命中分:SQL LIKE 拉候选 → 命中占比 + 文件名命中加权。"""
    scores = np.zeros(len(rels_s), dtype=np.float64)
    if not terms:
        return scores
    con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
    try:
        where = " OR ".join("(text LIKE ? OR rel_path LIKE ?)" for _ in terms[:12])
        args = [f"%{t}%" for t in terms[:12] for _ in range(2)]
        rows = con.execute(
            f"SELECT chunk_id, text, rel_path FROM chunks WHERE {where} LIMIT 4000",
            args).fetchall()
    except Exception:
        return scores
    finally:
        con.close()
    hit = {}
    for cid, text, rp in rows:
        s = sum(1 for t in terms if t in text or t in rp.lower())
        if s:
            hit[cid] = s / len(terms)
    for cid, s in hit.items():
        i = cid_to_idx.get(cid)
        if i is None:
            continue
        name = rels_s[i].lower()
        name_hit = sum(1 for t in terms if t in name)
        scores[i] = min(1.0, s + 0.4 * name_hit / max(1, len(terms)))
    return scores


def search(query: str, top_k: int = TOP_K, scope_dir: str | None = None,
           min_score: float = 0.0, mode: str | None = None) -> list[dict]:
    """检索。mode: hybrid(默认,语义+关键词 RRF 融合)/semantic/keyword。

    scope_dir 传相对目录前缀（如 '知识/'）过滤范围。
    """
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
    n = sub.shape[0]

    mode = mode or SEARCH_MODE
    terms = _terms(query)

    # 语义分(semantic/hybrid;失败时 hybrid 退关键词)
    sims = None
    if mode in ("hybrid", "semantic"):
        try:
            qv = embed_query(query)
            sims = sub @ qv                       # 向量已归一化,点积即余弦
        except Exception:
            if mode == "semantic":
                raise
            sims = None

    # 关键词分(hybrid/keyword)
    kw = np.zeros(n, dtype=np.float64)
    if mode in ("hybrid", "keyword") and terms:
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        try:
            where = " OR ".join("(text LIKE ? OR rel_path LIKE ?)" for _ in terms[:12])
            args = [f"%{t}%" for t in terms[:12] for _ in range(2)]
            rows = con.execute(
                f"SELECT chunk_id, text, rel_path FROM chunks WHERE {where} LIMIT 4000",
                args).fetchall()
            hit = {}
            for cid, text, rp in rows:
                s = sum(1 for t in terms if t in text or t in rp.lower())
                if s:
                    hit[cid] = s / len(terms)
            cid_to_idx = {int(c): i for i, c in enumerate(_all_ids_cache or [])}
            for cid, s in hit.items():
                i = cid_to_idx.get(cid)
                if i is not None:
                    name = rels_s[i].lower()
                    name_hit = sum(1 for t in terms if t in name)
                    kw[i] = min(1.0, s + 0.4 * name_hit / max(1, len(terms)))
        except Exception:
            pass
        finally:
            con.close()

    # 排序策略:
    #   semantic 强命中(top1 余弦 ≥ 阈值)→ 信任纯语义
    #   语义弱/离线 → 关键词 RRF 融合(精确文件名/术语查询拉精准命中)
    HYBRID_SEM_MIN = 0.35
    # 精确文件名直达:查询全串(去空格)是某文件路径的子串 → 该文件强制置顶。
    # 独立于融合模式,最可预测:查文件名 = 文件直达。
    q_flat = re.sub(r"[\s.]+", "", query).lower()
    name_exact = len(q_flat) >= 4 and any(
        q_flat in re.sub(r"[\/.]+", "", rp.lower())
        for rp in rels_s)
    if mode == "keyword" or (sims is None and mode == "hybrid"):
        if mode == "keyword":
            order = np.argsort(-kw)[:n]
            scores_final = kw[order]
        else:
            return []                        # 无任何可用信号
    elif mode == "hybrid" and use_sem_only:
        order = np.argsort(-sims)[:n]        # 语义强命中:不被关键词弱匹配稀释
        scores_final = sims[order]
    elif mode == "hybrid":
        sem_rank = np.empty(n, dtype=np.int64)
        sem_rank[np.argsort(-sims)] = np.arange(1, n + 1)
        kw_rank = np.full(n, 10 ** 6, dtype=np.int64)
        kw_idx = np.argsort(-kw)[: max(1, min(n, int((kw > 0).sum())) or 1)]
        kw_rank[kw_idx] = np.arange(1, len(kw_idx) + 1)
        fused = 1.0 / (60 + sem_rank) + np.where(kw_rank < 10**6,
                                                 1.0 / (60 + kw_rank), 0.0)
        order = np.argsort(-fused)[:n]
        scores_final = fused[order]
    else:
        order = np.argsort(-sims)[:n]
        scores_final = sims[order]

    order = order[: top_k * 8 if top_k * 8 < n else n]
    if name_exact:
        # 全量扫描置顶:目标文件可能语义分低而根本不在语义候选切片内
        pinned = [i for i, rp in enumerate(rels_s)
                  if q_flat in re.sub(r"[\/.]+", "", rp.lower())]
        rest = [i for i in order if i not in set(pinned)]
        order = list(pinned) + [int(i) for i in rest]
    out, seen_notes, seen_text = [], set(), set()
    for i in order:
        i = int(i)
        if rels_s[i] in seen_notes:       # 同一篇笔记只留最高分的一块
            continue
        th = hash(texts_s[i])
        if th in seen_text:               # 同内容多路重复(如重复上传)只留最高分
            continue
        seen_notes.add(rels_s[i])
        seen_text.add(th)
        out.append({"score": float(scores_final[i]), "rel_path": rels_s[i],
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
