# -*- coding: utf-8 -*-
"""索引器（LEGACY）：vault → 切块 → embedding → data/{rag.db, vectors.npy}

已由 indexer_qwen.py（SQLite BLOB 存储）取代，仅保留用于 LM Studio HTTP 端点场景。
产物走独立的 LEGACY_DB_PATH/LEGACY_VEC_PATH，与主库 qwen_rag.db 互不影响。

特性：
- vault 只读，产物全部落 data/
- 断点续传：按 (rel_path, mtime) 增量，重跑只处理新增/修改
- P0 目录优先：--p0 只跑高价值目录；默认全库
- 向量写入策略：会话内累积在内存，每 SAVE_EVERY 篇笔记原子落盘一次；
  崩溃后重启时若发现 chunks 表行数 > npy 行数，自动回滚多出的 DB 行再续传
"""
import sqlite3
import sys
import time
import traceback
from pathlib import Path

import numpy as np
import requests

from vault_rag.config import (VAULT, DATA_DIR, LEGACY_DB_PATH as DB_PATH,
                    LEGACY_VEC_PATH as VEC_PATH, API_URL, MODEL, DIM,
                    REQUEST_TIMEOUT, MAX_RETRIES, RETRY_BACKOFF,
                    P0_DIRS, SKIP_DIRS, ALIVE_PROBE_TIMEOUT)
from vault_rag.chunker import chunk_note

SAVE_EVERY = 3        # 每处理这么多篇笔记落盘一次向量（Qwen3 慢，缩短周期防丢数据）
BATCH_CHARS = 8000      # 单请求字符预算（Qwen 慢，用小批量加快落盘频率）


def http_embed(texts: list[str]) -> list[list[float]]:
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # 假活检测：短探针必须快速返回，否则推理引擎已死
            t0 = time.time()
            probe = requests.post(API_URL, json={"model": MODEL, "input": ["alive"]},
                                  timeout=(ALIVE_PROBE_TIMEOUT, ALIVE_PROBE_TIMEOUT))
            if probe.status_code != 200 or time.time() - t0 > ALIVE_PROBE_TIMEOUT:
                raise RuntimeError(f"假活检测失败: HTTP {probe.status_code} in {time.time()-t0:.1f}s")
            # 假活通过，发真实请求（timeout 传 tuple 避免 urllib3 用默认 1s 读超时）
            r = requests.post(API_URL, json={"model": MODEL, "input": texts},
                              timeout=(REQUEST_TIMEOUT, REQUEST_TIMEOUT))
            if r.status_code == 200:
                return [d["embedding"] for d in r.json()["data"]]
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:120]}")
        except Exception as e:
            if attempt == MAX_RETRIES:
                print(f"\n    ! embed 最终失败: {e}", flush=True)
                traceback.print_exc()
                return []
            wait = RETRY_BACKOFF * attempt
            print(f"    retry {attempt}/{MAX_RETRIES} after {wait}s ({type(e).__name__}: {str(e)[:80]})",
                  flush=True)
            time.sleep(wait)


def health_check() -> bool:
    """启动前探测端点：连续 3 次短请求，任一 5s 内 200 即视为可用。"""
    for i in range(3):
        try:
            t0 = time.time()
            r = requests.post(API_URL, json={"model": MODEL, "input": ["健康探针"]},
                              timeout=(15, 15))
            if r.status_code == 200 and time.time() - t0 < 5:
                print(f"[health] 端点正常（第 {i+1} 次探测 {time.time()-t0:.1f}s）", flush=True)
                return True
        except Exception:
            pass
        time.sleep(2)
    print("[health] 端点不可用或响应过慢，请检查 LM Studio 队列后重试", flush=True)
    return False


def init_db(con: sqlite3.Connection):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS notes(
            rel_path TEXT PRIMARY KEY, mtime REAL NOT NULL,
            n_chunks INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS chunks(
            chunk_id INTEGER PRIMARY KEY,   -- 与 vectors.npy 行号严格对应
            rel_path TEXT NOT NULL, seq INTEGER NOT NULL,
            section TEXT, text TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(rel_path);
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
    """)


def load_vectors() -> np.ndarray:
    if VEC_PATH.exists():
        return np.load(VEC_PATH, mmap_mode="r")
    return np.empty((0, DIM), dtype=np.float32)


def collect_notes(p0_only: bool) -> list[Path]:
    files = []
    roots = [VAULT / d for d in P0_DIRS] if p0_only else [VAULT]
    for root in roots:
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.md")):
            if not any(part in SKIP_DIRS for part in p.relative_to(VAULT).parts):
                files.append(p)
    return files


def reconcile(con: sqlite3.Connection) -> int:
    """崩溃恢复：DB 中 chunk_id 超出 npy 行数的行回滚（对应笔记删除待重索引）。"""
    n_vec = load_vectors().shape[0]
    stale = [r[0] for r in con.execute(
        "SELECT DISTINCT rel_path FROM chunks WHERE chunk_id >= ?", (n_vec,))]
    for rel in stale:
        con.execute("DELETE FROM chunks WHERE rel_path=?", (rel,))
        con.execute("DELETE FROM notes WHERE rel_path=?", (rel,))
    con.commit()
    if stale:
        print(f"[recover] 回滚 {len(stale)} 篇未落盘向量的笔记记录", flush=True)
    return len(stale)


def index(p0_only: bool):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    reconcile(con)

    base_vecs = load_vectors()
    base_n = base_vecs.shape[0]
    new_arrs: list[np.ndarray] = []      # 本会话新向量
    new_count = 0

    def vec_rows_now() -> int:
        return base_n + new_count

    done = {r[0]: r[1] for r in con.execute("SELECT rel_path, mtime FROM notes")}
    todo = []
    n_skip = 0
    for p in collect_notes(p0_only):
        rel = p.relative_to(VAULT).as_posix()
        mt = p.stat().st_mtime
        if rel in done and abs(done[rel] - mt) < 1:
            n_skip += 1
            continue
        todo.append((rel, p, mt))
    print(f"[scan] 待处理 {len(todo)} 篇 | 跳过已索引 {n_skip} 篇 | 已有向量 {base_n} 块",
          flush=True)
    if not todo:
        print("[done] 无需更新", flush=True)
        return

    t_start = time.time()
    n_note_done = 0
    since_save = 0
    batch: list[dict] = []

    def flush_batch():
        nonlocal new_count
        if not batch:
            return None
        embs = http_embed([b["text"] for b in batch])
        current = list(batch)
        batch.clear()
        if not embs or len(embs) != len(current):
            # 端点持续不可用或返回不齐：本批放弃，DB 未写入，下次重跑自动补
            return None
        arr = np.asarray(embs, dtype=np.float32)
        start_id = base_n + new_count
        con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)",
                        [(start_id + i, b["rel"], b["seq"], b["section"], b["text"])
                         for i, b in enumerate(current)])
        return arr

    pending_arrs: list[np.ndarray] = []

    def save_vectors(force=False):
        nonlocal new_arrs, new_count, pending_arrs, since_save
        if not force and since_save < SAVE_EVERY:
            return
        if not pending_arrs:
            con.commit()
            return
        stack = np.vstack([a for a in ([base_vecs] if base_n else []) + pending_arrs])
        # Windows 上 np.save 不能直接覆盖已有 .npy；临时文件必须带 .npy 后缀，
        # 否则 numpy 会自动补后缀生成 vectors.npy.tmp.npy 导致 rename 找不到源文件
        tmp = Path(str(VEC_PATH) + ".tmp.npy")
        np.save(tmp, stack)
        try:
            VEC_PATH.unlink(missing_ok=True)
        except FileNotFoundError:
            pass
        tmp.rename(VEC_PATH)
        pending_arrs = []
        con.commit()

    for rel, p, mt in todo:
        try:
            raw = p.read_text(encoding="utf-8", errors="replace")
            pieces = chunk_note(rel, raw)
        except Exception as e:
            print(f"\n    ! 读取/切块失败 {rel}: {e}", flush=True)
            continue
        for seq, b in enumerate(pieces):
            batch.append({"rel": rel, "seq": seq, "section": b.get("section", ""),
                          "text": b["text"]})
        try:
            if sum(len(b["text"]) for b in batch) >= BATCH_CHARS:
                arr = flush_batch()
                if arr is not None:
                    pending_arrs.append(arr)
                    new_count += arr.shape[0]

            # 该篇所有块的 embedding 都已发出；登记笔记并推进计数
            con.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (rel, mt, len(pieces)))
            n_note_done += 1
            since_save += 1
            elapsed = time.time() - t_start
            eta_min = elapsed / n_note_done * (len(todo) - n_note_done) / 60
            print(f"\r[{n_note_done}/{len(todo)}] {rel[:50]} | 块 {vec_rows_now()} "
                  f"| {elapsed:.0f}s | ETA ~{eta_min:.0f}min   ", end="", flush=True)
            save_vectors()
        except Exception:
            print(f"\n    ! 篇内异常（跳过继续）{rel}", flush=True)
            traceback.print_exc()
            continue

    # 收尾：编码残余批次
    arr = flush_batch()
    if arr is not None:
        pending_arrs.append(arr)
        new_count += arr.shape[0]
    save_vectors(force=True)
    con.execute("INSERT OR REPLACE INTO meta VALUES('indexed_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()
    total_chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    print(f"\n[done] 笔记累计 {con.execute('SELECT COUNT(*) FROM notes').fetchone()[0]} 篇，"
          f"总块数 {total_chunks}（本会话 +{new_count}），"
          f"耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)


if __name__ == "__main__":
    p0 = "--p0" in sys.argv
    rebuild = "--rebuild" in sys.argv
    if rebuild:
        for f in (DB_PATH, VEC_PATH):
            if f.exists():
                f.unlink()
    print(f"[mode] {'P0 高价值目录' if p0 else '全库'} | rebuild={rebuild}", flush=True)
    if not health_check():
        print("[exit] 端点未就绪，未做任何写入", flush=True)
        sys.exit(2)
    index(p0)
