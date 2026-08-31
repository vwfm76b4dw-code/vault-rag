# -*- coding: utf-8 -*-
"""webui_lib 纯逻辑测试（不起服务器、不调网络）。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vault_rag.webui_lib import (build_context_block, build_messages, chat_api_key,
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
            from vault_rag import scope
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
            from vault_rag import config, webui_lib
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
            from vault_rag import webui_lib
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
        from vault_rag import search
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
        from vault_rag import webui_lib
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


class TestUploadClassification(unittest.TestCase):
    """上传类型判定：扩展名优先，magic bytes 兜底（图像黑洞修复）。"""

    def test_image_by_extension(self):
        from vault_rag.webui_ext import classify_upload
        self.assertEqual(classify_upload("a.PNG", b"whatever"), "image")
        self.assertEqual(classify_upload("b.jpg", b""), "image")
        self.assertEqual(classify_upload("c.webp", b""), "image")

    def test_image_by_magic_even_renamed(self):
        from vault_rag.webui_ext import classify_upload
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
        self.assertEqual(classify_upload("fake.txt", png), "image")   # 改名也拦
        self.assertEqual(classify_upload("noext", b"\xff\xd8\xffE0"), "image")
        self.assertEqual(classify_upload("run.exe", b"MZ\x90\x00"), "binary")

    def test_text_passes(self):
        from vault_rag.webui_ext import classify_upload
        self.assertEqual(classify_upload("冒泡排序.cpp", b"#include <cstdio>"), "text")
        self.assertEqual(classify_upload("笔记.md", b"---\ntitle: x\n"), "text")
        # 文本误杀防线：普通笔记以 "BM"/"RIFF" 等 ASCII 开头不能被当二进制
        self.assertEqual(classify_upload("bmw笔记.md", "BMW 是巴伐利亚发动机制造厂".encode()), "text")


class TestUploadEndpoint(unittest.TestCase):
    """端点行为：图像/二进制显式拒绝（带原因）、不入盘、不写 include。"""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag import scope, webui_ext
        app = FastAPI()
        app.include_router(webui_ext.router)
        return TestClient(app), scope

    def test_png_rejected_md_saved(self):
        client, scope = self._client()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inc = td / "include.txt"; inc.write_text("# base\n", encoding="utf-8")
            from vault_rag import webui_ext as ext
            orig = (ext.UPLOAD_DIR, scope.INCLUDE_PATH)
            ext.UPLOAD_DIR = td / "uploads"
            scope.INCLUDE_PATH = inc
            try:
                png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
                r = client.post("/api/upload", files=[
                    ("files", ("star.png", png, "image/png")),
                    ("files", ("h.md", b"# hello\nworld", "text/markdown")),
                ])
                self.assertEqual(r.status_code, 200)
                d = r.json()
                self.assertTrue(d["ok"])
                self.assertEqual(len(d["saved"]), 1)
                self.assertIn("h.md", d["saved"][0])
                self.assertEqual(len(d["skipped"]), 1)
                self.assertIn("star.png", d["skipped"][0])
                self.assertIn("图片暂不支持", d["skipped"][0])
                # 关键：png 不落盘（旧版会写进 uploads 变成索引黑洞）
                saved_files = sorted(p.name for p in ext.UPLOAD_DIR.rglob("*") if p.is_file())
                self.assertEqual(saved_files, ["h.md"])
                # include.txt 只新增了 md 的 @ 规则
                text = inc.read_text(encoding="utf-8")
                self.assertIn("h.md", text)
                self.assertNotIn("star.png", text)
            finally:
                ext.UPLOAD_DIR, scope.INCLUDE_PATH = orig

    def test_png_only_fails_without_batch(self):
        client, scope = self._client()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inc = td / "include.txt"; inc.write_text("", encoding="utf-8")
            from vault_rag import webui_ext as ext
            orig = (ext.UPLOAD_DIR, scope.INCLUDE_PATH)
            ext.UPLOAD_DIR = td / "uploads"
            scope.INCLUDE_PATH = inc
            try:
                png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
                r = client.post("/api/upload", files=[("files", ("a.png", png, "image/png"))])
                self.assertEqual(r.status_code, 200)
                d = r.json()
                self.assertFalse(d["ok"])
                self.assertEqual(d["saved"], [])
                self.assertEqual(d["batch_dir"], "")
                self.assertIn("没有文件入库", d["message"])
                self.assertFalse(ext.UPLOAD_DIR.exists())      # 全拒时不建批次目录
            finally:
                ext.UPLOAD_DIR, scope.INCLUDE_PATH = orig


class TestRepoAdminEndpoints(unittest.TestCase):
    """仓库页后端端点：v1.2.0 前端就绪但路由漏接（404 坏页），补齐后回归。"""

    def _client(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag import webui_ext
        app = FastAPI()
        app.include_router(webui_ext.router)
        return TestClient(app)

    def _tmp_db(self, td: Path) -> Path:
        import sqlite3
        db = td / "qwen_rag.db"
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
            CREATE TABLE chunks(chunk_id INTEGER PRIMARY KEY, rel_path TEXT,
                seq INTEGER, section TEXT, text TEXT);
            CREATE TABLE blob_vectors(chunk_id INTEGER PRIMARY KEY);
            CREATE TABLE embed_cache(k TEXT PRIMARY KEY);
        """)
        con.execute("INSERT INTO notes VALUES('知识/a.md', 100, 2)")
        con.execute("INSERT INTO notes VALUES('研究/b.md', 200, 1)")
        con.executemany("INSERT INTO chunks VALUES(?,?,0,'','x')",
                        [(1, "知识/a.md"), (2, "知识/a.md"), (3, "研究/b.md")])
        con.executemany("INSERT INTO blob_vectors VALUES(?)", [(1,), (2,), (3,)])
        con.executemany("INSERT INTO embed_cache VALUES(?)", [("k1",), ("k2",)])
        con.commit(); con.close()
        return db

    def _patch_db(self, td: Path):
        from vault_rag import config
        orig = config.DB_PATH
        config.DB_PATH = self._tmp_db(td)
        return orig, config

    def test_stats_notes_delete_flow(self):
        client = self._client()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            orig, config = self._patch_db(td)
            try:
                s = client.get("/api/repo/stats").json()
                self.assertEqual(s["notes"], 2)
                self.assertEqual(s["chunks"], 3)
                self.assertTrue(s["consistent"])

                d = client.get("/api/repo/notes", params={"page": 1, "size": 15}).json()
                self.assertEqual(d["total"], 2)
                self.assertIn("知识", d["domains"])
                self.assertEqual(d["notes"][0]["vectors"], 1)   # 研究/b.md 最新在前
                self.assertIn("mtime_str", d["notes"][0])

                d2 = client.get("/api/repo/notes", params={"q": "a.md"}).json()
                self.assertEqual(d2["total"], 1)

                r = client.request("DELETE", "/api/repo/notes",
                                   json={"rel_path": "知识/a.md"})
                self.assertEqual(r.status_code, 200)
                self.assertEqual(r.json()["chunks_removed"], 2)
                s2 = client.get("/api/repo/stats").json()
                self.assertEqual(s2["notes"], 1)
                self.assertEqual(s2["chunks"], 1)

                r404 = client.request("DELETE", "/api/repo/notes",
                                      json={"rel_path": "不存在.md"})
                self.assertEqual(r404.status_code, 422)

                self.assertEqual(client.post("/api/repo/rebuild").json()["ok"], True)
                s3 = client.get("/api/repo/stats").json()
                self.assertEqual(s3["notes"], 0)
                self.assertEqual(s3["embed_cache"], 2)         # rebuild 保留 KV 缓存
                self.assertEqual(client.post("/api/repo/clear-cache").json()["cleared"], 2)
            finally:
                config.DB_PATH = orig

    def test_vacuum_reports_sizes(self):
        client = self._client()
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            orig, config = self._patch_db(td)
            try:
                r = client.post("/api/repo/vacuum").json()
                self.assertIn("before_mb", r)
                self.assertIn("after_mb", r)
            finally:
                config.DB_PATH = orig


if __name__ == "__main__":
    unittest.main()
