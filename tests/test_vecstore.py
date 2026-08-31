# -*- coding: utf-8 -*-
"""向量库对齐与检索正确性测试（核心回归）。

含关键回归：chunk_id 出现空洞后（删除越界笔记/崩溃回滚），文本与向量
必须仍然同行对齐——旧版 search.py 假设 id 连续，`vecs[ids]` 静默错配。
"""
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

DIM = 8


def make_vec(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    v = rng.normal(size=DIM).astype(np.float32)
    return v / np.linalg.norm(v)


def build_db(db_path: Path, n_chunks: int = 10, delete_ids: tuple = (3, 4, 5)):
    """建库：n_chunks 块 + 对齐向量，再删掉 delete_ids 制造 chunk_id 空洞。"""
    con = sqlite3.connect(db_path)
    con.executescript("""
        CREATE TABLE notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
        CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, rel_path TEXT,
            seq INTEGER, section TEXT, text TEXT);
        CREATE TABLE blob_vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
        CREATE TABLE embed_cache(h TEXT PRIMARY KEY, vec BLOB NOT NULL);
    """)
    rows, vecs = [], []
    for cid in range(n_chunks):
        text = f"chunk-{cid}-unique-text"
        rows.append((cid, f"知识/doc{cid % 3}.md", cid, "", text))
        vecs.append(make_vec(cid))
    con.executemany("INSERT INTO chunks VALUES(?,?,?,?,?)", rows)
    con.executemany("INSERT INTO blob_vectors VALUES(?,?)",
                    [(cid, v.tobytes()) for cid, v in enumerate(vecs)])
    for cid in delete_ids:                      # 制造空洞
        con.execute("DELETE FROM chunks WHERE chunk_id=?", (cid,))
        con.execute("DELETE FROM blob_vectors WHERE chunk_id=?", (cid,))
    con.commit()
    con.close()
    return {cid: vecs[cid] for cid in range(n_chunks) if cid not in delete_ids}


class TestFetchRowsAlignment(unittest.TestCase):
    def setUp(self):
        from vault_rag import search
        self.search = search
        self._orig = (search.DB_PATH, search.embed_query)
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "qwen_rag.db"
        self.expected = build_db(self.db)
        search.DB_PATH = self.db          # 指向测试库
        search._CACHE["stamp"] = None     # 清缓存

    def tearDown(self):
        self.search.DB_PATH, self.search.embed_query = self._orig
        self.search._CACHE["stamp"] = None
        self._tmp.cleanup()

    def test_join_pairs_text_with_own_vector(self):
        """删除产生空洞后，每个 chunk 的文本必须仍配上它自己的向量。"""
        rows = self.search.fetch_rows()
        self.assertEqual(len(rows), len(self.expected))
        for cid, rel, sec, text, blob in rows:
            want = self.expected[cid]
            got = np.frombuffer(blob, dtype=np.float32)
            np.testing.assert_array_equal(got, want)
            self.assertEqual(text, f"chunk-{cid}-unique-text")

    def test_search_hits_expected_top1(self):
        """向量 self-hit：用某块的原始向量当查询，top1 必须还是那块文本。"""
        target_cid = 7
        qv = self.expected[target_cid]
        self.search.embed_query = lambda _q: qv        # 桩掉模型编码
        out = self.search.search("任意查询", top_k=5, mode="semantic")  # 纯语义通道
        self.assertEqual(out[0]["text"], f"chunk-{target_cid}-unique-text")

    def test_scope_dir_filter(self):
        qv = self.expected[7]
        self.search.embed_query = lambda _q: qv
        out = self.search.search("任意查询", scope_dir="知识/doc1.md")
        for r in out:
            self.assertTrue(r["rel_path"].startswith("知识/doc1.md"))

    def test_cache_invalidated_on_db_change(self):
        before = self.search.fetch_rows()
        con = sqlite3.connect(self.db)                 # 再删一块 → 库变了
        con.execute("DELETE FROM blob_vectors WHERE chunk_id=9")
        con.commit()
        con.close()
        after = self.search.fetch_rows()
        self.assertEqual(len(after), len(before) - 1)


class TestReconcile(unittest.TestCase):
    """indexer_qwen.reconcile：孤向量删、缺向量 chunk 连同笔记回滚。"""

    def test_reconcile_removes_orphans_and_rolls_back(self):
        from vault_rag import indexer_qwen
        with tempfile.TemporaryDirectory() as td:
            db = Path(td) / "q.db"
            con = sqlite3.connect(db)
            indexer_qwen.init_db(con)
            con.execute("INSERT INTO chunks VALUES(1,'a.md',0,'','t1')")
            con.execute("INSERT INTO chunks VALUES(2,'b.md',0,'','t2')")
            con.execute("INSERT INTO notes VALUES('a.md',1.0,1)")
            con.execute("INSERT INTO notes VALUES('b.md',1.0,1)")
            con.execute("INSERT INTO blob_vectors VALUES(1,?)", (make_vec(1).tobytes(),))
            con.execute("INSERT INTO blob_vectors VALUES(99,?)", (make_vec(2).tobytes(),))
            indexer_qwen.reconcile(con)
            chunks = {r[0] for r in con.execute("SELECT chunk_id FROM chunks")}
            blobs = {r[0] for r in con.execute("SELECT chunk_id FROM blob_vectors")}
            notes = {r[0] for r in con.execute("SELECT rel_path FROM notes")}
            con.close()
            self.assertEqual(chunks, {1})            # 缺向量的 b.md 连带回滚
            self.assertEqual(blobs, {1})             # 孤向量 99 删除
            self.assertEqual(notes, {"a.md"})


if __name__ == "__main__":
    unittest.main()
