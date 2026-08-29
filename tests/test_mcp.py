# -*- coding: utf-8 -*-
"""rag_mcp 核心逻辑测试（FastMCP 可用时才跑）。

含关键回归：hybrid_search 曾查询 blob_vectors 的 'id' 列（实际是 chunk_id），
该工具此前必然 OperationalError。
"""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

try:
    import rag_mcp  # noqa: F401
    import search
    HAVE_MCP = True
except ImportError:
    HAVE_MCP = False

DIM = 8


@unittest.skipUnless(HAVE_MCP, "mcp 未安装，跳过 rag_mcp 测试")
class TestHybridSearch(unittest.TestCase):
    def setUp(self):
        import rag_mcp
        self.rag_mcp = rag_mcp
        self.search = search
        # 保存原值，tearDown 恢复，防止桩泄漏到其他测试
        self._orig = (search.DB_PATH, search.embed_query,
                      rag_mcp._embed_query, rag_mcp.RAG_DB)
        self._tmp = tempfile.TemporaryDirectory()
        db = Path(self._tmp.name) / "qwen_rag.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
            CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, rel_path TEXT,
                seq INTEGER, section TEXT, text TEXT);
            CREATE TABLE blob_vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
            CREATE TABLE embed_cache(h TEXT PRIMARY KEY, vec BLOB NOT NULL);
        """)
        qv = np.random.default_rng(7).normal(size=DIM).astype(np.float32)
        qv /= np.linalg.norm(qv)
        for cid, text in enumerate(["agent 防遗忘研究", "RAG 索引踩坑", "无关内容"]):
            con.execute("INSERT INTO chunks VALUES(?,?,?,?,?)",
                        (cid, f"知识/d{cid}.md", 0, "", text))
            v = qv if cid == 0 else np.random.default_rng(cid).normal(size=DIM).astype(np.float32)
            con.execute("INSERT INTO blob_vectors VALUES(?,?)", (cid, v.tobytes()))
        con.commit()
        con.close()
        rag_mcp.RAG_DB = db
        search.DB_PATH = db
        search._CACHE["stamp"] = None
        self.qv = qv
        rag_mcp._MODEL_CACHE["model"] = object()      # 跳过真实模型加载
        rag_mcp._embed_query = lambda _q: qv
        search.embed_query = lambda _q: qv            # semantic_search 走 search 模块

    def tearDown(self):
        s, r = self.search, self.rag_mcp
        s.DB_PATH, s.embed_query, r._embed_query, r.RAG_DB = self._orig
        s._CACHE["stamp"] = None
        self._tmp.cleanup()

    def test_hybrid_no_operationalerror_and_ranked(self):
        """回归：旧 SQL 用 'id' 列必崩；修复后语义/关键词融合正常出结果。"""
        out = self.rag_mcp.hybrid_search.fn("agent 防遗忘") if hasattr(
            self.rag_mcp.hybrid_search, "fn") else self.rag_mcp.hybrid_search("agent 防遗忘")
        self.assertIn("results", out)
        self.assertGreater(len(out["results"]), 0)
        top = out["results"][0]
        self.assertEqual(top["path"], "知识/d0.md")   # 语义最近 + 关键词命中双高

    def test_semantic_search_via_shared_search(self):
        out = self.rag_mcp.semantic_search.fn("agent 防遗忘") if hasattr(
            self.rag_mcp.semantic_search, "fn") else self.rag_mcp.semantic_search("agent 防遗忘")
        self.assertEqual(out["count"], 3)
        self.assertEqual(out["results"][0]["path"], "知识/d0.md")


if __name__ == "__main__":
    unittest.main()
