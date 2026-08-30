# -*- coding: utf-8 -*-
"""热点笔记重编码器：从 nomic 全库索引中挑出高频/高价值笔记，用 Qwen3-8B 重编码。

策略：
1. 从 nomic 的 chunks 表里按 rel_path 聚合，找出块数最多的 Top N 篇（通常是高价值长笔记）
2. 用 Qwen3 对这些笔记重新生成 4096 维向量，存入 data/qwen/
3. 同时支持手动指定笔记路径列表

用法：
    python hotspot_indexer.py --top 30          # 自动选块数最多的30篇
    python hotspot_indexer.py --top 30 --search "agent"   # 在 agent 相关笔记里选30篇
    python hotspot_indexer.py --paths path1.md path2.md   # 手动指定
    python hotspot_indexer.py --search "RAG" --top 20
"""
import argparse
import sqlite3
import sys
import time
import os
from pathlib import Path

import numpy as np
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vault_rag.config import VAULT, DATA_DIR, LEGACY_DB_PATH, LEGACY_VEC_PATH

NOMIC_DB = LEGACY_DB_PATH
NOMIC_VEC = LEGACY_VEC_PATH
OUT_DIR = DATA_DIR / "qwen"
OUT_DB = OUT_DIR / "rag.db"
OUT_VEC = OUT_DIR / "vectors.npy"
API_URL = "http://127.0.0.1:1234/v1/embeddings"
MODEL = "text-embedding-qwen3-embedding-8b"
DIM = 4096
SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", ".codex"}
REQUEST_TIMEOUT = (120, 120)   # Qwen3 慢，给足余量
MAX_ATTEMPTS = 4


def http_embed(texts: list[str]) -> list[list[float]]:
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            r = requests.post(API_URL, json={"model": MODEL, "input": texts},
                              timeout=REQUEST_TIMEOUT)
            if r.status_code == 200:
                return [d["embedding"] for d in r.json()["data"]]
            raise RuntimeError(f"HTTP {r.status_code}")
        except Exception as e:
            if attempt == MAX_ATTEMPTS:
                print(f"  ! embed 失败: {e}", file=sys.stderr)
                return []
            time.sleep(5 * attempt)
    return []


def init_out_db():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(OUT_DB)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chunks(
            chunk_id INTEGER PRIMARY KEY, rel_path TEXT, seq INTEGER,
            section TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    con.commit()
    return con


def collect_hot_notes(top: int, search: str | None) -> list[Path]:
    """从 nomic 索引结果中选热点笔记。"""
    con = sqlite3.connect(NOMIC_DB)
    if search:
        rows = con.execute(
            "SELECT rel_path, COUNT(*) as cnt FROM chunks "
            "WHERE rel_path LIKE ? GROUP BY rel_path ORDER BY cnt DESC LIMIT ?",
            (f"%{search}%", top)).fetchall()
    else:
        rows = con.execute(
            "SELECT rel_path, COUNT(*) as cnt FROM chunks "
            "GROUP BY rel_path ORDER BY cnt DESC LIMIT ?", (top,)).fetchall()

    notes = []
    for rel, cnt in rows:
        p = VAULT / rel.replace("/", "\\")
        if p.exists() and not any(part in SKIP_DIRS for part in p.relative_to(VAULT).parts):
            notes.append(p)
        else:
            # fallback: 直接按 rel 拼路径
            p2 = VAULT / Path(rel)
            if p2.exists():
                notes.append(p2)
    con.close()
    print(f"[选篇] 选出 {len(notes)} 篇热点笔记", flush=True)
    return notes


def collect_manual_paths(paths: list[str]) -> list[Path]:
    notes = []
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            # 尝试在 vault 里找
            p = VAULT / p_str.replace("/", "\\")
            if not p.exists():
                p = VAULT / p_str
        if p.exists() and p.suffix == ".md":
            notes.append(p)
    return notes


def simple_chunk(text: str, max_chars: int = 600) -> list[str]:
    """简单切块：按 max_chars 滑动窗口，重叠 60 字符。"""
    out, start = [], 0
    while start < len(text):
        end = min(start + max_chars, len(text))
        out.append(text[start:end])
        start = end - 60 if start + 60 < len(text) else end
        if start >= len(text):
            break
    return [p for p in (x.strip() for x in out) if p]


def index_hotspots(notes: list[Path], con: sqlite3.Connection):
    n_ids = 0
    t0 = time.time()
    for i, p in enumerate(notes, 1):
        rel = p.relative_to(VAULT).as_posix()
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            pieces = simple_chunk(raw)
        except Exception as e:
            print(f"  ! 读取失败 {rel}: {e}", file=sys.stderr)
            continue
        embs = http_embed(pieces)
        if not embs:
            print(f"  ! embed 返回空，跳过 {rel}", file=sys.stderr)
            continue
        arr = np.asarray(embs, dtype=np.float32)
        start_id = n_ids
        # 写 npy（带 .npy 后缀避免 Windows 覆盖问题）
        tmp = OUT_VEC.with_suffix(".tmp.npy")
        if OUT_VEC.exists():
            old = np.load(OUT_VEC, mmap_mode="r")
            np.save(tmp, np.vstack([old, arr]))
            del old
        else:
            np.save(tmp, arr)
        try:
            OUT_VEC.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        tmp.rename(OUT_VEC)
        n_ids += arr.shape[0]
        con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)",
                        [(start_id + j, rel, j, "", t) for j, t in enumerate(pieces)])
        con.commit()
        dt = time.time() - t0
        eta = dt / i * (len(notes) - i)
        print(f"  [{i}/{len(notes)}] {rel.split('/')[-1][:40]} | {len(pieces)} 块 | "
              f"{dt:.0f}s | ETA {eta/60:.0f}min   ", end="\r", flush=True)
    print()
    return n_ids


def search(query: str, top_k: int = 5) -> list[dict]:
    if not OUT_VEC.exists():
        return []
    probe = http_embed([query])
    if not probe:
        return []
    qv = np.asarray(probe[0], dtype=np.float32)
    qv /= np.linalg.norm(qv)
    vecs = np.load(OUT_VEC, mmap_mode="r")
    vecs = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
    sims = vecs @ qv
    order = np.argsort(-sims)[:top_k]
    con = sqlite3.connect(OUT_DB)
    by_id = {r[0]: r for r in con.execute(
        "SELECT chunk_id, rel_path, text FROM chunks WHERE chunk_id IN ({})".format(
            ",".join(str(int(i)) for i in order)))}
    con.close()
    # IN 查询不保证返回顺序，按 order 重建配对，避免分数与文本错位
    out = []
    for i in order:
        r = by_id.get(int(i))
        if r is not None:
            out.append({"score": float(sims[int(i)]), "rel_path": r[1], "text": r[2][:150]})
    return out


def fmt(results):
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.3f}] {r['rel_path'].split('/')[-1][:50]}")
        print(f"   {r['text']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="热点笔记 Qwen3 重编码")
    ap.add_argument("--top", type=int, default=30, help="自动选篇数（按块数降序）")
    ap.add_argument("--search", type=str, default=None, help="只选标题/内容含此关键词的笔记")
    ap.add_argument("--paths", nargs="*", default=None, help="手动指定笔记路径（相对 vault 或绝对路径）")
    ap.add_argument("--query", type=str, default=None, help="检索测试（不索引）")
    ap.add_argument("--rebuild", action="store_true", help="清空上次输出")
    args = ap.parse_args()

    if args.rebuild and OUT_DIR.exists():
        import shutil
        shutil.rmtree(OUT_DIR)

    if args.query:
        print(f"\n=== Qwen3 检索: {args.query} ===\n")
        fmt(search(args.query))
        sys.exit(0)

    if args.paths:
        notes = collect_manual_paths(args.paths)
    else:
        notes = collect_hot_notes(args.top, args.search)

    if not notes:
        print("没有选到任何笔记，退出。")
        sys.exit(0)

    con = init_out_db()
    total_chunks = index_hotspots(notes, con)
    con.execute("INSERT OR REPLACE INTO meta VALUES('indexed_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()
    total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"[done] {len(notes)} 篇笔记，{total} 块，路径: {OUT_DB}")
    print(f"\n试搜: python hotspot_indexer.py --query 'agent 如何不忘事'")
