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


if __name__ == "__main__":
    unittest.main()
