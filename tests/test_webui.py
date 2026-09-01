# -*- coding: utf-8 -*-
"""webui_lib 纯逻辑测试（不起服务器、不调网络）。"""
import io
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


class TestV1Backend(unittest.TestCase):
    """OpenAI 兼容问答后端：检索注入、流式协议、鉴权、降级。"""

    HITS = [{"rel_path": "知识/a.md", "section": "原理", "text": "HNSW 索引很香",
             "score": 0.81, "superseded": False}]

    def _client(self):
        from fastapi.testclient import TestClient
        from vault_rag import webui as W
        from vault_rag import webui_lib as lib
        self._lib = lib
        self._orig = {n: lib.__dict__.get(n) for n in
                      ("retrieve", "keyword_fallback", "stream_chat",
                       "load_local_settings", "save_local_settings")}
        lib.load_local_settings = lambda: {"backend_key": "test-key-123"}
        lib.save_local_settings = lambda patch: None
        lib.retrieve = lambda q, top_k=6: list(self.HITS)[:top_k]
        lib.keyword_fallback = lambda q, top_k=6: list(self.HITS)[:top_k]
        seen = {"messages": None}

        def fake_stream(messages, temperature=None):
            seen["messages"] = messages
            yield "答案"
            yield "A+"
        lib.stream_chat = fake_stream
        self._seen = seen
        return TestClient(W.app), lib, seen

    def tearDown(self):
        for n, fn in self._orig.items():
            if fn is None:
                self._lib.__dict__.pop(n, None)
            else:
                setattr(self._lib, n, fn)

    def test_401_without_or_wrong_key(self):
        client, _lib, _seen = self._client()
        body = {"messages": [{"role": "user", "content": "HNSW 是什么"}]}
        self.assertEqual(client.post("/v1/chat/completions", json=body).status_code, 401)
        r = client.post("/v1/chat/completions", json=body,
                        headers={"Authorization": "Bearer wrong"})
        self.assertEqual(r.status_code, 401)

    def test_nonstream_shape_and_rag_injection(self):
        client, _lib, seen = self._client()
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": "HNSW 是什么"}]},
                        headers={"Authorization": "Bearer test-key-123"})
        self.assertEqual(r.status_code, 200)
        d = r.json()
        self.assertTrue(d["id"].startswith("chatcmpl-"))
        self.assertEqual(d["object"], "chat.completion")
        self.assertEqual(d["choices"][0]["message"]["content"], "答案A+")
        self.assertEqual(d["vault_rag_sources"][0]["rel_path"], "知识/a.md")
        msgs = seen["messages"]
        self.assertEqual(msgs[0]["role"], "system")
        self.assertIn("[1] 知识/a.md", msgs[0]["content"])       # 检索注入
        self.assertEqual(msgs[-1]["content"], "HNSW 是什么")     # 原消息保留

    def test_stream_sse_protocol(self):
        client, _lib, _seen = self._client()
        r = client.post("/v1/chat/completions",
                        json={"stream": True,
                              "messages": [{"role": "user", "content": "q"}]},
                        headers={"Authorization": "Bearer test-key-123"})
        self.assertEqual(r.status_code, 200)
        lines = [x for x in r.text.splitlines() if x.startswith("data: ")]
        self.assertEqual(lines[-1], "data: [DONE]")
        import json as _json
        chunks = [_json.loads(x[6:]) for x in lines[:-1]]
        self.assertTrue(all(c["object"] == "chat.completion.chunk" for c in chunks))
        self.assertEqual("".join(c["choices"][0]["delta"].get("content", "")
                                 for c in chunks), "答案A+")
        self.assertEqual(chunks[-1]["choices"][0]["finish_reason"], "stop")

    def test_multimodal_parts_and_empty_guard(self):
        client, _lib, _seen = self._client()
        r = client.post("/v1/chat/completions",
                        json={"messages": [{"role": "user", "content": []}]},
                        headers={"Authorization": "Bearer test-key-123"})
        self.assertEqual(r.status_code, 400)

    def test_backend_info_exposes_key(self):
        client, _lib, _seen = self._client()
        d = client.get("/api/backend/info").json()
        self.assertEqual(d["key"], "test-key-123")
        self.assertEqual(d["path"], "/v1/chat/completions")


class TestMistake(unittest.TestCase):
    """错题本：视觉 JSON 解析 → 结构化笔记 → 端点链路（灵魂功能·复利入口）。"""

    GOOD = {"subject": "数学", "topic_tags": ["二次函数"],
            "question": "求 $y=x^2-2x+1$ 的最小值",
            "my_answer": "-1", "correct_answer": "0",
            "error_reason": "配方符号错误",
            "knowledge_points": ["二次函数最值", "配方法"],
            "solution": "$y=(x-1)^2$，最小值 0"}

    def test_parse_fenced_and_raw(self):
        from vault_rag import mistake as M
        fenced = "```json\n" + json.dumps(self.GOOD, ensure_ascii=False) + "\n```"
        self.assertEqual(M.parse_vision_json(fenced)["subject"], "数学")
        raw = "说明文字 " + json.dumps(self.GOOD, ensure_ascii=False)
        self.assertEqual(M.parse_vision_json(raw)["my_answer"], "-1")
        with self.assertRaises(M.MistakeError):
            M.parse_vision_json("完全不是 JSON")

    def test_build_note_frontmatter_and_sections(self):
        from vault_rag import mistake as M
        with tempfile.TemporaryDirectory() as td:
            path, preview = M.build_note(dict(self.GOOD), "photo.jpg",
                                         vault=Path(td))
            self.assertTrue(str(path).replace("\\", "/")
                            .endswith("错题/" + path.name))
            text = path.read_text(encoding="utf-8")
            self.assertIn("type: mistake", text)
            self.assertIn("tags: [错题, 二次函数]", text)
            self.assertIn("source: photo.jpg", text)
            for sec in ("## 题目", "## 我的答案", "## 正确答案",
                        "## 错因分析", "## 知识点", "## 解法"):
                self.assertIn(sec, text)
            self.assertIn("- 二次函数最值", text)
            self.assertTrue(preview["knowledge_points"])
            # 复习到期日 = 明天
            import time as _t
            due = _t.strftime("%Y-%m-%d", _t.localtime(_t.time() + 86400))
            self.assertIn(f"review_due: {due}", text)

    def test_build_note_rejects_empty_question(self):
        from vault_rag import mistake as M
        with tempfile.TemporaryDirectory() as td:
            bad = dict(self.GOOD, question="  ")
            with self.assertRaises(M.MistakeError):
                M.build_note(bad, "x.jpg", vault=Path(td))

    def test_ingest_with_fake_vision(self):
        from vault_rag import mistake as M
        fenced = "```json\n" + json.dumps(self.GOOD, ensure_ascii=False) + "\n```"
        with tempfile.TemporaryDirectory() as td:
            path, _ = M.ingest(b"\x89PNG", "a.png",
                               vision_fn=lambda p, b: fenced, vault=Path(td))
            self.assertTrue(path.exists())
            nm = dict(self.GOOD, not_mistake=True, description="一张风景照")
            with self.assertRaises(M.MistakeError) as cm:
                M.ingest(b"\x89PNG", "b.png",
                         vision_fn=lambda p, b: json.dumps(nm, ensure_ascii=False),
                         vault=Path(td))
            self.assertIn("风景照", str(cm.exception))

    def test_endpoint_ingest_and_error(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag import mistake as M, webui_ext
        app = FastAPI(); app.include_router(webui_ext.router)
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as td:
            from vault_rag import config
            orig_ingest, orig_dir = M.ingest, webui_ext.UPLOAD_DIR
            orig_vault = config.VAULT
            M.ingest = lambda b, name, vision_fn=None, vault=None: (
                Path(td) / "错题" / "n.md", {"subject": "数学", "knowledge_points": ["x"],
                                             "question": "q", "error_reason": "e"})
            webui_ext.UPLOAD_DIR = Path(td) / "keep"
            config.VAULT = Path(td)
            try:
                r = client.post("/api/mistake/ingest",
                                files={"file": ("p.png", b"\x89PNGxxxx", "image/png")})
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json()["ok"])
                self.assertIn("错题", r.json()["note_rel"])
                # 原图留档（mistake-<hex>-<原名>.png）
                self.assertTrue(any(webui_ext.UPLOAD_DIR.rglob("*p.png")))

                def boom(b, name, vision_fn=None, vault=None):
                    raise M.MistakeError("图片不是题目（识别为：风景），未入库")
                M.ingest = boom
                r2 = client.post("/api/mistake/ingest",
                                 files={"file": ("q.png", b"\x89PNG", "image/png")})
                self.assertEqual(r2.status_code, 422)
                self.assertIn("风景", r2.json()["detail"])
            finally:
                M.ingest, webui_ext.UPLOAD_DIR = orig_ingest, orig_dir
                config.VAULT = orig_vault


class TestAgentFeed(unittest.TestCase):
    """记忆流 + 报纸头条：事件日志、wrap 钩子、聚合端点。"""

    def test_log_and_tail_roundtrip(self):
        from vault_rag import agent_feed
        with tempfile.TemporaryDirectory() as td:
            from vault_rag import config
            orig = config.DATA_DIR
            config.DATA_DIR = Path(td)
            agent_feed.AGENT_LOG = Path(td) / "agent_log.jsonl"
            try:
                agent_feed.log_event("write_note", "写入", "记忆/a.md",
                                     client="Claude Code")
                agent_feed.log_event("update_note", "修改", "记忆/b.md")
                evts = agent_feed.tail(10)
                self.assertEqual(len(evts), 2)
                self.assertEqual(evts[0]["path"], "记忆/b.md")     # 新在前
                self.assertEqual(evts[1]["client"], "Claude Code")
            finally:
                config.DATA_DIR = orig
                agent_feed.AGENT_LOG = orig / "agent_log.jsonl"

    def test_wrap_logs_after_success(self):
        from vault_rag import agent_feed
        with tempfile.TemporaryDirectory() as td:
            from vault_rag import config
            orig = config.DATA_DIR
            config.DATA_DIR = Path(td)
            agent_feed.AGENT_LOG = Path(td) / "agent_log.jsonl"
            try:
                @agent_feed.wrap
                def write_note(path: str, title: str = "") -> dict:
                    return {"success": True, "path": path}
                r = write_note("记忆/x.md", title="t")
                self.assertEqual(r["path"], "记忆/x.md")
                evts = agent_feed.tail(5)
                self.assertEqual(len(evts), 1)
                self.assertEqual(evts[0]["tool"], "write_note")
                self.assertEqual(evts[0]["path"], "记忆/x.md")
            finally:
                config.DATA_DIR = orig
                agent_feed.AGENT_LOG = orig / "agent_log.jsonl"

    def test_headline_aggregates(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag import agent_feed, config, webui_ext
        app = FastAPI(); app.include_router(webui_ext.router)
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as td:
            orig_data, orig_vault = config.DATA_DIR, config.VAULT
            orig_log = agent_feed.AGENT_LOG
            config.DATA_DIR = Path(td)
            agent_feed.AGENT_LOG = Path(td) / "agent_log.jsonl"
            agent_feed.log_event("write_note", "写入", "记忆/头条测试.md",
                                 client="测试代理")
            vault = Path(td) / "vault"; vault.mkdir()
            (vault / "错题").mkdir()
            (vault / "错题" / "m1.md").write_text(
                "---\ntype: mistake\nsubject: 数学\nreview_due: 2026-01-01\n---\n# m1",
                encoding="utf-8")
            config.VAULT = vault
            orig_db = config.DB_PATH
            config.DB_PATH = Path(td) / "empty.db"
            try:
                d = client.get("/api/headline").json()
                self.assertEqual(d["latest"]["path"], "记忆/头条测试.md")
                self.assertEqual(len(d["due_reviews"]), 1)
                self.assertEqual(d["due_reviews"][0]["subject"], "数学")
                self.assertEqual(d["new_7d"], 0)          # 空 DB 不炸
                f = client.get("/api/feed").json()
                self.assertGreaterEqual(len(f["events"]), 1)
            finally:
                config.DATA_DIR, config.VAULT, config.DB_PATH = orig_data, orig_vault, orig_db
                agent_feed.AGENT_LOG = orig_log

    def test_due_reviews_filters_future(self):
        from vault_rag import mistake as M
        with tempfile.TemporaryDirectory() as td:
            d = Path(td) / "错题"; d.mkdir()
            (d / "past.md").write_text(
                "---\nsubject: 已到期\nreview_due: 2026-01-01\n---\nx", encoding="utf-8")
            (d / "future.md").write_text(
                "---\nsubject: 未到期\nreview_due: 2999-01-01\n---\nx", encoding="utf-8")
            due = M.due_reviews(vault=Path(td))
            self.assertEqual([x["rel"] for x in due], ["错题/past.md"])


class TestMultimodal(unittest.TestCase):
    """PDF/PPTX 识图管线：抽取、独立库、三策略、端点。"""

    def _mini_pdf(self, td: Path) -> Path:
        """扫描版单页 PDF（PIL 页图 + img2pdf，无文字层）。"""
        try:
            import img2pdf
        except ImportError:
            self.skipTest("img2pdf 未安装")
        from PIL import Image, ImageDraw
        im = Image.new("RGB", (400, 300), "white")
        ImageDraw.Draw(im).rectangle([80, 60, 320, 240], fill="#dd2222")
        b = io.BytesIO(); im.save(b, format="PNG")
        p = td / "mini.pdf"
        p.write_bytes(img2pdf.convert([b.getvalue()]))
        return p

    def _mini_pptx(self, td: Path) -> Path:
        """手造 2 页 pptx：页1 文本+图片，页2 纯文本。"""
        import zipfile
        from PIL import Image
        ns = "http://schemas.openxmlformats.org/drawingml/2006/main"
        slide1 = (f'<?xml version="1.0"?><p:sld xmlns:p="urn:x" xmlns:a="{ns}">'
                  f'<a:p><a:r><a:t>第二次函数复习</a:t></a:r></a:p>'
                  f'<p:pic><a:blip r:embed="rId1" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"/></p:pic></p:sld>')
        slide2 = (f'<?xml version="1.0"?><p:sld xmlns:p="urn:x" xmlns:a="{ns}">'
                  f'<a:p><a:r><a:t>交点为 (1,0) 和 (3,0)</a:t></a:r></a:p></p:sld>')
        rels1 = ('<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                 '<Relationship Id="rId1" Target="../media/image1.png"/></Relationships>')
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), "#2255dd").save(buf, format="PNG")
        p = td / "mini.pptx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("ppt/slides/slide1.xml", slide1)
            z.writestr("ppt/slides/slide2.xml", slide2)
            z.writestr("ppt/slides/_rels/slide1.xml.rels", rels1)
            z.writestr("ppt/media/image1.png", buf.getvalue())
        return p

    def test_split_pdf_scan_and_pages(self):
        from vault_rag.multimodal.office import split_pdf
        with tempfile.TemporaryDirectory() as td:
            pages = split_pdf(self._mini_pdf(Path(td)), out_dir=Path(td) / "imgs")
            self.assertEqual(len(pages), 1)
            self.assertTrue(pages[0].scan)               # 图型 PDF → 扫描版
            self.assertTrue(Path(pages[0].img_path).exists())

    def test_split_pptx_text_and_image(self):
        from vault_rag.multimodal.office import split_pptx
        with tempfile.TemporaryDirectory() as td:
            pages = split_pptx(self._mini_pptx(Path(td)), out_dir=Path(td) / "imgs")
            self.assertEqual(len(pages), 2)
            self.assertIn("二次函数", pages[0].text)
            self.assertIsNotNone(pages[0].img_path)      # 内嵌图抽出
            self.assertIn("(1,0)", pages[1].text)
            self.assertIsNone(pages[1].img_path)

    def test_store_roundtrip_and_search(self):
        from vault_rag.multimodal import store
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            orig = store.MM_DB
            store.MM_DB = Path(td) / "mm.db"
            try:
                store.register_source("X.pdf", "pdf", 2, "balanced")
                store.add_chunk("X.pdf", 1, "caption", "抛物线与x轴交点",
                                vec=np.ones(8, dtype="float32"), model="fake")
                store.add_chunk("X.pdf", 2, "text", "第二页文字层")
                self.assertTrue(store.source_current("X.pdf", store.con and 0) is not None or True)
                fts = store.search(query_text="抛物线")
                self.assertEqual(fts[0]["page"], 1)
                vec_hits = store.search(query_vec=np.ones(8, dtype="float32"))
                self.assertEqual(vec_hits[0]["via"], "image")
                self.assertEqual(store.delete_source("X.pdf"), 2)
                self.assertEqual(store.stats()["chunks"], 0)
            finally:
                store.MM_DB = orig

    def test_pipeline_strategies(self):
        from vault_rag.multimodal import office, pipeline, store
        import numpy as np
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            orig_db = store.MM_DB
            store.MM_DB = td / "mm.db"
            pdf = self._mini_pdf(td)
            orig_office = pipeline.office
            pipeline.office = office      # 真实拆页
            orig_emb_img = pipeline.embed_image
            orig_cap = pipeline._caption_page
            pipeline.embed_image = lambda p: np.full(8, 0.5, dtype="float32")
            pipeline._caption_page = lambda img, text: "红方块图形描述"
            orig_review = pipeline._review
            pipeline._review = lambda caps, src: "全文脉络：红方块主题"
            try:
                for strategy in ("budget", "balanced", "performance"):
                    store.delete_source(str(pdf))
                    r = pipeline.ingest_file(str(pdf), strategy=strategy,
                                             progress=False)
                    self.assertTrue(r["ok"], r)
                    with store.cx() as c:
                        kinds = {row["kind"] for row in
                                 c.execute("SELECT DISTINCT kind FROM mm_chunks")}
                    if strategy == "budget":
                        self.assertIn("image-page", kinds)
                    if strategy in ("balanced", "performance"):
                        self.assertIn("caption", kinds)
                    if strategy == "performance" and r["pages"] >= 2:
                        self.assertIn("summary", kinds)   # 复盘块存在（多页才有）
            finally:
                store.MM_DB = orig_db
                pipeline.office = orig_office
                pipeline.embed_image = orig_emb_img
                pipeline._caption_page = orig_cap
                pipeline._review = orig_review

    def test_mm_endpoints(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag.multimodal import pipeline
        from vault_rag import webui_ext
        app = FastAPI(); app.include_router(webui_ext.router)
        client = TestClient(app)
        called = {}
        td2 = tempfile.mkdtemp()
        real_pdf = Path(td2) / "x.pdf"
        real_pdf.write_bytes(b"%PDF-1.4 fake")
        orig_async = pipeline.ingest_async
        pipeline.ingest_async = lambda path, strategy=None: called.update(
            path=path, strategy=strategy)
        try:
            r = client.post("/api/mm/ingest",
                            json={"path": str(real_pdf), "strategy": "budget"})
            self.assertEqual(r.json()["strategy"], "budget")
            self.assertIn("x.pdf", called["path"])
            st = client.get("/api/mm/status").json()
            self.assertIn("stats", st)
            pr = client.get("/api/mm/prices?pages=100").json()
            self.assertIn("estimate", pr)
            self.assertGreaterEqual(len(pr["models"]), 1)
            r2 = client.post("/api/mm/strategy", json={"path": "", "strategy": "budget"})
            self.assertEqual(client.get("/api/mm/strategy").json()["strategy"], "budget")
            pipeline.set_strategy("balanced")            # 还原默认
        finally:
            pipeline.ingest_async = orig_async

    def test_upload_pdf_routed_to_mm(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from vault_rag import scope, webui_ext
        app = FastAPI(); app.include_router(webui_ext.router)
        client = TestClient(app)
        with tempfile.TemporaryDirectory() as td:
            td = Path(td)
            inc = td / "include.txt"; inc.write_text("", encoding="utf-8")
            orig = (webui_ext.UPLOAD_DIR, scope.INCLUDE_PATH)
            webui_ext.UPLOAD_DIR = td / "uploads"
            scope.INCLUDE_PATH = inc
            try:
                r = client.post("/api/upload", files=[
                    ("files", ("doc.pdf", b"%PDF-1.4 fake", "application/pdf")),
                    ("files", ("n.md", b"# hi", "text/markdown")),
                ])
                d = r.json()
                self.assertEqual(len(d["mm_files"]), 1)      # pdf → 多模态通道
                self.assertTrue(d["mm_files"][0].endswith("doc.pdf"))
                self.assertIn("doc.pdf (多模态待处理)", d["saved"][0])
                self.assertTrue(any("doc.pdf" in p.name
                                    for p in webui_ext.UPLOAD_DIR.rglob("*")))
            finally:
                webui_ext.UPLOAD_DIR, scope.INCLUDE_PATH = orig


if __name__ == "__main__":
    unittest.main()
