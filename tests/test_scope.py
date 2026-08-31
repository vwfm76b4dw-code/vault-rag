# -*- coding: utf-8 -*-
"""scope.py 单元测试：规则解析、行序覆盖语义、隐藏目录、外部文件。

通过注入 rules（parse_rules(text)）测试匹配逻辑，不触碰真实 vault；
collect_files 语义等价性用临时目录 + VAULT_PATH 环境变量验证。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class TestParseRules(unittest.TestCase):
    def test_basic_kinds(self):
        from vault_rag import scope
        rules = scope.parse_rules("知识/\n*.md\n!知识/旧/\n")
        kinds = [r[0] for r in rules]
        self.assertEqual(kinds, ["include", "include", "exclude"])

    def test_external_with_alias(self):
        from vault_rag import scope
        rules = scope.parse_rules("@C:/x/CLAUDE.md as external/AI.md")
        self.assertEqual(rules[0][0], "external")
        self.assertEqual(rules[0][2], "external/AI.md")

    def test_external_relative_raises(self):
        from vault_rag import scope
        with self.assertRaises(ValueError):
            scope.parse_rules("@relative/path.md")

    def test_comments_blank_ignored(self):
        from vault_rag import scope
        self.assertEqual(scope.parse_rules("# 注释\n\n   \n"), [])

    def test_dir_rule_requires_slash_boundary(self):
        from vault_rag import scope
        (kind, pred) = scope.parse_rules("知识/")[0]
        self.assertTrue(pred("知识/原理/x.md"))
        self.assertFalse(pred("知识库/x.md"))      # 前缀必须到目录边界

    def test_glob_not_cross_directory(self):
        from vault_rag import scope
        (kind, pred) = scope.parse_rules("*.md")[0]
        self.assertTrue(pred("根级.md"))
        self.assertFalse(pred("知识/子.md"))


class TestCollectFiles(unittest.TestCase):
    def _collect(self, rules_text: str, vault: Path):
        from vault_rag import scope
        rules = scope.parse_rules(rules_text)
        orig_vault = scope.VAULT
        scope.VAULT = vault                    # 指向临时 vault，不碰真实数据
        try:
            return dict(scope.collect_files(rules, include_uploads=False))
        finally:
            scope.VAULT = orig_vault

    def test_include_exclude_order_semantics(self):
        """最后一条命中的规则决定去留：后写 include 重新捞回先写 exclude。"""
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            (vault / "知识").mkdir()
            (vault / "知识" / "a.md").write_text("a", encoding="utf-8")
            (vault / "笔记").mkdir()
            (vault / "笔记" / "b.md").write_text("b", encoding="utf-8")
            # 排除一切之后，笔记/ 又被捞回
            got = self._collect("!知识/\n!笔记/\n笔记/\n", vault)
            self.assertIn("笔记/b.md", got)
            self.assertNotIn("知识/a.md", got)

    def test_hidden_dirs_always_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            hidden = vault / ".obsidian"
            hidden.mkdir()
            (hidden / "x.md").write_text("x", encoding="utf-8")
            (vault / "y.md").write_text("y", encoding="utf-8")
            got = self._collect("*.md\n", vault)
            self.assertEqual(list(got), ["y.md"])

    def test_external_missing_silently_skipped(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            got = self._collect(f"@{td}/不存在.md as external/ghost.md\n", vault)
            self.assertEqual(got, {})

    def test_external_added_and_excludable(self):
        with tempfile.TemporaryDirectory() as td:
            vault = Path(td)
            ext = Path(td) / "ext.md"
            ext.write_text("e", encoding="utf-8")
            got = self._collect(f"@{ext}\n", vault)
            self.assertEqual(list(got), ["external/ext.md"])
            # 其后的 exclude 可排除外部文件
            got2 = self._collect(f"@{ext}\n!external/\n", vault)
            self.assertEqual(got2, {})


class TestUploadsAutoInclude(unittest.TestCase):
    """回归:uploads 自动纳入不能被跨调用去重状态误杀（49 cpp 下线事故）。"""

    def test_uploads_persist_across_calls(self):
        import tempfile
        from vault_rag import config, scope
        with tempfile.TemporaryDirectory() as td:
            up = Path(td) / "uploads" / "batch1"
            up.mkdir(parents=True)
            (up / "a.cpp").write_text("// same content", encoding="utf-8")
            import vault_rag.config as cfg
            orig_data = cfg.DATA_DIR
            orig_cache = dict(scope._up_hash_cache)
            cfg.DATA_DIR = Path(td)          # collect_files 函数内动态读取
            scope._up_hash_cache.clear()
            try:
                r1 = dict(scope.collect_files([], include_uploads=True))
                r2 = dict(scope.collect_files([], include_uploads=True))
                self.assertIn("uploads/batch1/a.cpp", r1)
                self.assertIn("uploads/batch1/a.cpp", r2)   # 事故回归点
                up2 = Path(td) / "uploads" / "batch2"
                up2.mkdir(parents=True)
                (up2 / "b.cpp").write_text("// same content", encoding="utf-8")
                r3 = dict(scope.collect_files([], include_uploads=True))
                self.assertNotIn("uploads/batch1/a.cpp", r3)   # 旧副本去重
                self.assertIn("uploads/batch2/b.cpp", r3)      # 保留最新
                self.assertEqual(len([k for k in r3 if k.endswith(".cpp")]), 1)
            finally:
                cfg.DATA_DIR = orig_data
                scope._up_hash_cache = orig_cache


if __name__ == "__main__":
    unittest.main()
