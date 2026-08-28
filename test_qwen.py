# -*- coding: utf-8 -*-
"""Qwen3 小规模测试：选 10 篇笔记索引，验证质量与稳定性。

用法：
    python test_qwen.py               # 默认 10 篇
    python test_qwen.py --count 30    # 改篇数
    python test_qwen.py --rebuild     # 清空上次测试数据
"""
import argparse
import shutil
import sqlite3
import sys
import time
import os
import os
import os
from pathlib import Path

import numpy as np
import requests

VAULT = Path(os.environ.get("VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault")))
OUT_DIR = Path(r"D:\AI Coding\vault-rag\data\qwen")
DB_PATH = OUT_DIR / "rag.db"
VEC_PATH = OUT_DIR / "vectors.npy"
API_URL = "http://127.0.0.1:1234/v1/embeddings"
MODEL = "text-embedding-qwen3-embedding-8b"
DIM = 4096
TOP_K = 5
SKIP_DIRS = {".obsidian", ".trash", ".git", "__pycache__", ".codex"}


def http_embed(texts: list[str]) -> list[list[float]]:
    r = requests.post(API_URL, json={"model": MODEL, "input": texts}, timeout=120)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:100]}")
    return [d["embedding"] for d in r.json()["data"]]


def init_db():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chunks(
            chunk_id INTEGER PRIMARY KEY, rel_path TEXT, seq INTEGER,
            section TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """)
    con.commit()
    return con


def collect_notes(count: int) -> list[Path]:
    files = sorted(VAULT.rglob("*.md"))
    skip = [f for f in files if any(p in SKIP_DIRS for p in f.relative_to(VAULT).parts)]
    return [f for f in files if f not in skip][:count]


def chunk_text(text: str) -> list[str]:
    """简单按 ~600 字符切块。"""
    out, start = [], 0
    while start < len(text):
        end = min(start + 600, len(text))
        out.append(text[start:end])
        start = end
    return out


def index_sample(notes: list[Path], con: sqlite3.Connection):
    n_ids = 0
    t0 = time.time()
    for i, p in enumerate(notes, 1):
        rel = p.relative_to(VAULT).as_posix()
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            pieces = chunk_text(raw)
        except Exception as e:
            print(f"  ! 读取失败 {rel}: {e}", file=sys.stderr)
            continue
        embs = http_embed(pieces)
        arr = np.asarray(embs, dtype=np.float32)
        start_id = n_ids
        tmp = Path(str(VEC_PATH) + ".tmp.npy")
        if VEC_PATH.exists():
            old = np.load(VEC_PATH, mmap_mode="r")
            np.save(tmp, np.vstack([old, arr]))
            del old  # 释放 mmap 锁，否则 Windows 上 unlink 会 PermissionError
        else:
            np.save(tmp, arr)
        try:
            VEC_PATH.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        tmp.rename(VEC_PATH)
        n_ids += arr.shape[0]
        con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)",
                        [(start_id + j, rel, j, "", t) for j, t in enumerate(pieces)])
        con.commit()
        dt = time.time() - t0
        eta = dt / i * (len(notes) - i)
        print(f"  [{i}/{len(notes)}] {rel.split('/')[-1][:40]} | {len(pieces)} 块 | "
              f"{dt:.0f}s | ETA {eta/60:.0f}min   ", end="\r", flush=True)
    print()
    return len(notes)


def search(query: str, top_k: int = TOP_K) -> list[dict]:
    if not VEC_PATH.exists():
        return []
    probe = http_embed([query])
    qv = np.asarray(probe[0], dtype=np.float32)
    qv /= np.linalg.norm(qv)
    vecs = np.load(VEC_PATH, mmap_mode="r")
    vecs /= np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-9)
    sims = vecs @ qv
    order = np.argsort(-sims)[:top_k]
    con = sqlite3.connect(DB_PATH)
    rows = con.execute("SELECT rel_path, text FROM chunks WHERE chunk_id IN ({})".format(
        ",".join(str(int(i)) for i in order))).fetchall()
    return [{"score": float(sims[int(i)]), "rel_path": r[0], "text": r[1][:150]}
            for i, r in zip(order, rows)]


def fmt(results):
    for i, r in enumerate(results, 1):
        print(f"{i}. [{r['score']:.3f}] {r['rel_path'].split('/')[-1][:50]}")
        print(f"   {r['text']}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=10)
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--search", nargs="?", const="", default=None, metavar="QUERY")
    args = ap.parse_args()

    if args.rebuild and OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    if args.search is not None:
        q = args.search if args.search else input("搜索: ")
        print(f"\n=== 搜索: {q} ===\n")
        fmt(search(q))
        sys.exit(0)

    con = init_db()
    notes = collect_notes(args.count)
    print(f"[test] {len(notes)} 篇笔记，Qwen3-8B，dim={DIM}")
    index_sample(notes, con)
    total = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"[done] {total} 块，路径: {DB_PATH}")
    print("\n试搜：python test_qwen.py --search 'agent 如何不忘事'")
