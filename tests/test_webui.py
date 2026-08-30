# -*- coding: utf-8 -*-
"""webui_lib 纯逻辑测试（不起服务器、不调网络）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from webui_lib import (build_context_block, build_messages, chat_api_key,
                       create_note, load_local_settings, save_local_settings,
                       save_scope_text, validate_scope_text)


class TestChatPrompt(unittest.TestCase):
    def test_build_messages_with_chunks(self):
        chunks = [{"rel_path": "知识/a.md", "section": "原理", "text": "HNSW 索引很香",
                   "superseded": False},
                  {"rel_path": "研究/b.md", "section": "", "text": "旧内容",
                   "superseded": True}]
        msgs = build_messages("怎么建索引?", chunks)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "system")
        ctx = msgs[1]["content"]
        self.assertIn("[1] 知识/a.md", ctx)
        self.assertIn("已被更新版本取代", ctx)          # superseded 警示注入
        self.assertIn("怎么建索引?", ctx)

    def test_build_messages_empty(self):
        msgs = build_messages("q", [])
        self.assertIn("未检索到相关片段", msgs[1]["content"])

    def test_context_block_escapes_whitespace(self):
        block = build_context_block(
            [{"rel_path": "a.md", "section": "", "text": "多\n行\t文本", "superseded": False}])
        self.assertNotIn("\n行", block.split("[1]")[1].splitlines()[-1])


class TestScopeValidate(unittest.TestCase):
    def test_valid_text_passes(self):
        self.assertEqual(validate_scope_text("知识/\n# 注释\n*.md\n"), [])

    def test_relative_external_rejected(self):
        errs = validate_scope_text("@relative/path.md")
        self.assertEqual(len(errs), 1)
        self.assertIn("绝对路径", errs[0])

    def test_missing_external_rejected(self):
        errs = validate_scope_text("@C:/definitely/not/exists.md")
        self.assertEqual(len(errs), 1)
        self.assertIn("不存在", errs[0])

    def test_save_rejects_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            import scope
            orig = scope.INCLUDE_PATH
            scope.INCLUDE_PATH = Path(td) / "include.txt"
            try:
                self.assertEqual(save_scope_text("@bad-relative\n"),
                                 ["第1行: @ 外部路径必须是绝对路径"])
                self.assertFalse(scope.INCLUDE_PATH.exists())   # 拒绝时不能写坏文件
                self.assertEqual(save_scope_text("# ok\n"), [])
                self.assertTrue(scope.INCLUDE_PATH.exists())
            finally:
                scope.INCLUDE_PATH = orig


class TestLocalSettings(unittest.TestCase):
    def test_roundtrip_and_key_priority(self):
        with tempfile.TemporaryDirectory() as td:
            import config, webui_lib
            orig = (config.LOCAL_SETTINGS_PATH, webui_lib.LOCAL_SETTINGS_PATH)
            p = Path(td) / "_local_settings.json"
            config.LOCAL_SETTINGS_PATH = webui_lib.LOCAL_SETTINGS_PATH = p
            try:
                save_local_settings({"agnes_key": "sk-test-123"})
                self.assertEqual(load_local_settings()["agnes_key"], "sk-test-123")
                self.assertEqual(chat_api_key(), "sk-test-123")
                # 环境变量优先于本地文件
                import os
                os.environ["AGNES_API_KEY"] = "sk-env-456"
                try:
                    self.assertEqual(chat_api_key(), "sk-env-456")
                finally:
                    del os.environ["AGNES_API_KEY"]
            finally:
                config.LOCAL_SETTINGS_PATH, webui_lib.LOCAL_SETTINGS_PATH = orig


class TestCreateNote(unittest.TestCase):
    def test_creates_with_frontmatter_and_rejects_escape(self):
        with tempfile.TemporaryDirectory() as td:
            import webui_lib
            orig = webui_lib.VAULT
            webui_lib.VAULT = Path(td)
            try:
                ok, rel = create_note("知识/新主题.md", "正文")
                self.assertTrue(ok)
                target = Path(td) / "知识" / "新主题.md"
                self.assertTrue(target.exists())
                self.assertIn("created:", target.read_text(encoding="utf-8"))

                ok2, _ = create_note("知识/新主题.md", "x")     # 不覆盖
                self.assertFalse(ok2)
                ok3, _ = create_note("../逃逸.md", "x")
                self.assertFalse(ok3)
                ok4, _ = create_note("知识/x.md", "y", overwrite=True)
                self.assertTrue(ok4)
            finally:
                webui_lib.VAULT = orig


class TestEmbedBackend(unittest.TestCase):
    """查询向量策略：默认 HTTP 端点优先（零本地模型加载），离线抛 EmbedUnavailable。"""

    def test_http_first_and_offline_raises(self):
        import threading, json as _json
        from http.server import BaseHTTPRequestHandler, HTTPServer
        import numpy as _np

        class H(BaseHTTPRequestHandler):
            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                v = _np.zeros(4, dtype=_np.float32); v[0] = 1
                body = _json.dumps({"data": [{"embedding": v.tolist()}]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            def log_message(self, *a): pass

        srv = HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        import search
        orig = (search.EMBED_HTTP_URL, search.EMBED_BACKEND)
        search.EMBED_HTTP_URL = f"http://127.0.0.1:{srv.server_port}/v1/embeddings"
        search.EMBED_BACKEND = "http"
        try:
            v = search.embed_query("测试")            # 在线 → HTTP 向量
            self.assertEqual(v.argmax(), 0)
            search.EMBED_HTTP_URL = "http://127.0.0.1:1/v1/embeddings"
            with self.assertRaises(search.EmbedUnavailable):
                search.embed_query("测试")             # 离线 → 明确抛错（调用方关键词兜底）
        finally:
            search.EMBED_HTTP_URL, search.EMBED_BACKEND = orig
            srv.shutdown()


class TestKeywordFallback(unittest.TestCase):
    """关键词兜底：中文 2-gram 切分，整句短语也能部分命中。"""

    def _db(self, td: Path):
        import sqlite3
        db = Path(td) / "q.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
            CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, rel_path TEXT,
                seq INTEGER, section TEXT, text TEXT);
        """)
        con.execute("INSERT INTO chunks VALUES(1,'知识/a.md',0,'','介绍 GitHub 优质项目与开源趋势')")
        con.execute("INSERT INTO chunks VALUES(2,'知识/b.md',0,'','RAG 索引分块与向量存储实践')")
        con.commit(); con.close()
        return db

    def test_bigram_matches_partial_phrase(self):
        import webui_lib
        with tempfile.TemporaryDirectory() as td:
            orig = webui_lib.DB_PATH
            webui_lib.DB_PATH = self._db(Path(td))
            try:
                out = webui_lib.keyword_fallback("github优质项目有哪些", top_k=3)
                self.assertGreater(len(out), 0)              # 旧版整句 LIKE 为空
                self.assertEqual(out[0]["rel_path"], "知识/a.md")
                out2 = webui_lib.keyword_fallback("完全无关的查询词组xyz", top_k=3)
                self.assertIsInstance(out2, list)
            finally:
                webui_lib.DB_PATH = orig


if __name__ == "__main__":
    unittest.main()
