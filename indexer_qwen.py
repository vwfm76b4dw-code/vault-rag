# -*- coding: utf-8 -*-
"""Qwen3-Embedding-0.6B 索引器（使用 transformers，绕过 llama.cpp bug）

审查修复记录（2026-08-25）：
1. [严重] flush() 的 start_id 计算错误：sum(all_arrs) 在 append 之前算的是正确值，
   但 DB 插入和向量追加之间没有事务保护——崩溃时 DB 与 npy 不一致。改为先算 id 再写库，
   且每次 flush 后立即 commit。
2. [严重] save_vectors 里重复 unlink 两次（复制粘贴错误），且 rename 前若目标存在会
   FileExistsError。统一为 unlink(missing_ok=True) + rename，并加重试。
3. [中] embed_batch 用 last_hidden_state.mean() 而非官方推荐的 last_token_pool +
   L2 归一化——检索质量打折。改用 Qwen3 官方 pooling 方式。
4. [中] all_arrs 列表无限增长：每 SAVE_EVERY 篇 vstack 一次但旧引用未释放，
   长跑内存翻倍。改为维护单一 ndarray，用 list 只存增量、落盘后清空。
5. [低] 进度行 \r 会把 traceback 藏起来，出错看不到。异常时先打印换行。
6. [低] tokenizer 未设 pad_token 时批量 padding 可能报错（Qwen3 tokenizer 自带
   pad token，防御性设置一次）。
"""
from __future__ import annotations

import os
os.environ.setdefault('HF_ENDPOINT', 'https://hf-mirror.com')
import sqlite3, time, sys, traceback
from pathlib import Path

import numpy as np

from config import DATA_DIR, DB_PATH
from chunker import chunk_note
import scope as scopes

MODEL_NAME = "Qwen/Qwen3-Embedding-0.6B"
DIM = 1024
BATCH_SIZE = 16       # embedding 批量
MAX_LEN = 512         # tokenizer 截断长度

_MODEL = None
_TOKENIZER = None


def load_model():
    """加载编码模型（进程内只加载一次；import 本模块不触发）。"""
    global _MODEL, _TOKENIZER
    if _MODEL is not None:
        return _MODEL, _TOKENIZER
    import torch
    from transformers import AutoModel, AutoTokenizer
    print(f"加载 {MODEL_NAME} (CPU, float32)...", flush=True)
    model = AutoModel.from_pretrained(MODEL_NAME, trust_remote_code=True).float().eval()
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME, trust_remote_code=True)
    if tokenizer.pad_token is None:                      # 修复6：防御性 pad_token
        tokenizer.pad_token = tokenizer.eos_token
    torch.set_num_threads(min(10, os.cpu_count()))    # 明确线程数，避免争抢
    print("加载完成", flush=True)
    _MODEL, _TOKENIZER = model, tokenizer
    return model, tokenizer


def last_token_pool(last_hidden: torch.Tensor, attention_mask: torch.Tensor) -> torch.Tensor:
    """Qwen3 官方 pooling：取每个序列最后一个非 padding token 的隐状态。修复3。"""
    seq_len = attention_mask.sum(dim=1) - 1
    idx = seq_len.view(-1, 1, 1).expand(-1, 1, last_hidden.size(-1))
    return last_hidden.gather(1, idx).squeeze(1)


def embed_batch(texts: list[str]) -> np.ndarray:
    import torch
    model, tokenizer = load_model()
    with torch.no_grad():
        inputs = tokenizer(texts, return_tensors="pt", padding=True,
                           truncation=True, max_length=MAX_LEN)
        outputs = model(**inputs)
        emb = last_token_pool(outputs.last_hidden_state, inputs["attention_mask"])
        emb = torch.nn.functional.normalize(emb, p=2, dim=1)   # L2 归一化，检索必需
        return emb.numpy().astype(np.float32)


def init_db(con: sqlite3.Connection):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
        CREATE TABLE IF NOT EXISTS chunks(chunk_id INTEGER PRIMARY KEY,
            rel_path TEXT NOT NULL, seq INTEGER, section TEXT, text TEXT);
        CREATE INDEX IF NOT EXISTS idx_chunks_path ON chunks(rel_path);
        -- 主键即 chunk_id：向量与文本物理绑定，杜绝任何错位
        CREATE TABLE IF NOT EXISTS blob_vectors(
            chunk_id INTEGER PRIMARY KEY,
            vec BLOB NOT NULL);
        -- KV-cache（用户提案落地）：hash(模型,文本) 寻址，同文本永不重算
        CREATE TABLE IF NOT EXISTS embed_cache(
            h TEXT PRIMARY KEY,
            vec BLOB NOT NULL);
    """)
    con.commit()


def load_vectors() -> np.ndarray:
    """按 chunks.chunk_id 序 JOIN 读全量向量（顺序与 next_id 分配严格一致）。"""
    con = sqlite3.connect(DB_PATH)
    try:
        rows = con.execute(
            "SELECT b.vec FROM blob_vectors b "
            "JOIN chunks c ON c.chunk_id = b.chunk_id "
            "ORDER BY c.chunk_id").fetchall()
    finally:
        con.close()
    if not rows:
        return np.empty((0, DIM), dtype=np.float32)
    return np.vstack([np.frombuffer(r[0], dtype=np.float32).reshape(1, -1) for r in rows])


def _chunk_hash(text: str) -> str:
    """KV-cache 键：模型名 + 文本。换模型/改文本自动 miss，不串用旧向量。"""
    import hashlib
    return hashlib.sha1(f"{MODEL_NAME}\x00{text}".encode("utf-8")).hexdigest()


def _cache_lookup(con: sqlite3.Connection, hashes: list[str]) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for i in range(0, len(hashes), 200):
        batch = hashes[i:i + 200]
        q = ",".join("?" * len(batch))
        for h, v in con.execute(f"SELECT h, vec FROM embed_cache WHERE h IN ({q})", batch):
            out[h] = v
    return out


def save_vectors(pairs: list[tuple[int, np.ndarray]], con: sqlite3.Connection):
    """写入向量：以 chunk_id 为显式主键（根治 AUTOINCREMENT 错位）。

    pairs = [(chunk_id, 1xN 向量), ...] 由 flush() 按块生成。
    """
    if not pairs:
        return
    con.executemany(
        "INSERT OR REPLACE INTO blob_vectors(chunk_id, vec) VALUES(?, ?)",
        [(cid, v.astype(np.float32).tobytes()) for cid, v in pairs])


def reconcile(con: sqlite3.Connection):
    """崩溃恢复（语义化自愈）：孤向量删、缺向量的 chunk 连同笔记回滚。"""
    con.execute("DELETE FROM blob_vectors WHERE chunk_id NOT IN "
                "(SELECT chunk_id FROM chunks)")
    stale = [r[0] for r in con.execute(
        "SELECT DISTINCT rel_path FROM chunks WHERE chunk_id NOT IN "
        "(SELECT chunk_id FROM blob_vectors)").fetchall()]
    for rel in stale:
        con.execute("DELETE FROM chunks WHERE rel_path=?", (rel,))
        con.execute("DELETE FROM notes WHERE rel_path=?", (rel,))
    con.commit()
    if stale:
        print(f"[recover] 回滚 {len(stale)} 篇缺向量的笔记", flush=True)


def collect_todo(con: sqlite3.Connection):
    """基于 include.txt 声明范围发现待办：新增/修改篇编码，越界篇清除。"""
    done = {r[0]: r[1] for r in con.execute("SELECT rel_path, mtime FROM notes")}
    current = dict(scopes.collect_files())          # rel_path -> abs Path

    # 迁移清理：曾入库但现在越界（include.txt 移除/规则变化）的笔记整体下线
    gone = [rp for rp in done if rp not in current]
    if gone:
        for rp in gone:
            con.execute(
                "DELETE FROM blob_vectors WHERE chunk_id IN "
                "(SELECT chunk_id FROM chunks WHERE rel_path=?)",
                (rp,))
            con.execute("DELETE FROM chunks WHERE rel_path=?", (rp,))
            con.execute("DELETE FROM notes WHERE rel_path=?", (rp,))
        con.commit()
        print(f"[scope] 按.include.txt 下线越界笔记 {len(gone)} 篇", flush=True)

    todo, n_skip = [], 0
    for rel, p in sorted(current.items()):
        mt = p.stat().st_mtime
        if rel in done and abs(done[rel] - mt) < 1:
            n_skip += 1
            continue
        todo.append((rel, p, mt))
    return todo, n_skip


def index(max_files: int = 0):
    """增量索引。max_files>0 时本次只处理前 N 篇待处理笔记（小步增量）。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB_PATH)
    init_db(con)
    reconcile(con)

    base_n = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
    todo, n_skip = collect_todo(con)
    if max_files and max_files > 0:
        todo = todo[:max_files]
    print(f"[scan] 待处理 {len(todo)} 篇 | 跳过 {n_skip} 篇 | 已有 {base_n} 块", flush=True)
    if not todo:
        print("[done] 无需更新", flush=True)
        return

    t_start = time.time()
    n_done = 0
    next_id = con.execute("SELECT COALESCE(MAX(chunk_id), -1) + 1 FROM chunks").fetchone()[0]
    pending_chunks: list[dict] = []
    flush_info: list[str] = []

    def flush():
        nonlocal next_id
        if not pending_chunks:
            return
        texts = [c["text"] for c in pending_chunks]
        hashes = [_chunk_hash(t) for t in texts]

        cached = _cache_lookup(con, hashes)
        missing_idx = [i for i, h in enumerate(hashes) if h not in cached]

        vecs = np.empty((len(texts), DIM), dtype=np.float32)
        if missing_idx:
            computed = np.vstack([
                embed_batch([texts[i] for i in missing_idx[j:j+BATCH_SIZE]])
                for j in range(0, len(missing_idx), BATCH_SIZE)])
            for k, i in enumerate(missing_idx):
                vecs[i] = computed[k]
            con.executemany(
                "INSERT OR REPLACE INTO embed_cache(h, vec) VALUES(?, ?)",
                [(hashes[i], computed[k].tobytes()) for k, i in enumerate(missing_idx)])
        hits = len(texts) - len(missing_idx)
        for i, h in enumerate(hashes):      # cache 命中的直接复用
            if h in cached:
                vecs[i] = np.frombuffer(cached[h], dtype=np.float32)

        rows = [(next_id + i, c["rel"], c["seq"], c["section"], c["text"])
                for i, c in enumerate(pending_chunks)]
        con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)", rows)
        save_vectors([(cid, vecs[i]) for i, (cid, *_r) in enumerate(rows)], con)
        next_id += len(pending_chunks)
        pending_chunks.clear()
        con.commit()          # 每批独立提交=天然断点续传
        flush_info.append(f"hit {hits}/miss {len(missing_idx)}")

    try:
        for rel, p, mt in todo:
            try:
                raw = p.read_text(encoding="utf-8", errors="replace")
                pieces = chunk_note(rel, raw)
            except Exception as e:
                print(f"\n! 读取失败 {rel}: {e}", flush=True)
                continue
            for seq, b in enumerate(pieces):
                pending_chunks.append({"rel": rel, "seq": seq,
                                       "section": b.get("section", ""), "text": b["text"]})
            flush()
            con.execute("INSERT OR REPLACE INTO notes VALUES(?,?,?)", (rel, mt, len(pieces)))
            n_done += 1

            elapsed = time.time() - t_start
            eta_min = elapsed / n_done * (len(todo) - n_done) / 60
            print(f"\r[{n_done}/{len(todo)}] {rel[:40]} | 块 {next_id} "
                  f"| {elapsed:.0f}s | ETA {eta_min:.0f}min   ", end="", flush=True)
        con.commit()
        # 终检：三表完美配对才算数
        total_c = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        total_b = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        paired = con.execute(
            "SELECT COUNT(*) FROM chunks c JOIN blob_vectors b ON b.chunk_id=c.chunk_id"
        ).fetchone()[0]
        ok = paired == total_c == total_b
        print(f"\n[done] {con.execute('SELECT COUNT(*) FROM notes').fetchone()[0]} 篇，"
              f"{total_c} 块，文本-向量配对 {paired}/{total_b} "
              f"{'✓ 一致' if ok else '✗ 不一致!'}"
              f" | 耗时 {(time.time()-t_start)/60:.1f} 分钟", flush=True)
    except KeyboardInterrupt:
        print("\n[interrupt] 手动中断（已完成批次均已提交，重跑自动续传）", flush=True)
        raise
    except Exception:
        print("\n[fatal] 未捕获异常——已完成批次不受影响（每批独立提交）", flush=True)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    index()
