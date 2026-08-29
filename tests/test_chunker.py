# -*- coding: utf-8 -*-
"""chunker.py 单元测试：标题分段、frontmatter 块、滑窗、section 标签正确性。"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from chunker import chunk_markdown, chunk_note, _split_long


class TestSplitLong(unittest.TestCase):
    def test_short_untouched(self):
        self.assertEqual(_split_long("短文本" * 10), ["短文本" * 10])

    def test_too_short_dropped(self):
        self.assertEqual(_split_long("  ab  "), [])

    def test_long_sliding_window(self):
        text = "字" * 2000          # MAX_CHARS=700 → 3 块
        pieces = _split_long(text)
        self.assertGreater(len(pieces), 1)
        for p in pieces:
            self.assertLessEqual(len(p), 700)

    def test_tail_merged_into_previous(self):
        text = "甲" * 690 + "乙"          # 尾部 <30 字碎片应并入前块
        pieces = _split_long(text)
        self.assertEqual(pieces[-1].endswith("乙"), True)


class TestChunkMarkdown(unittest.TestCase):
    BODY = "这是足够长的正文内容，确保超过最小块字符数限制。" * 3   # >30 字

    def test_heading_sections(self):
        md = f"# 总览\n{self.BODY}\n## 子节\n{self.BODY}\n"
        secs = chunk_markdown(md)
        self.assertEqual(secs[0][0], "总览")
        self.assertEqual(secs[1][0], "总览 › 子节")

    def test_title_with_bracket_keeps_section(self):
        # 回归：标题含 ']' 时旧版按文本前缀解析会截断 section
        md = f"# 使用[方括号]标题\n{self.BODY}"
        for section, piece in chunk_markdown(md):
            self.assertEqual(section, "使用[方括号]标题")

    def test_no_heading(self):
        secs = chunk_markdown(self.BODY)
        self.assertEqual(secs[0][0], "")

    def test_empty_section_dropped(self):
        secs = chunk_markdown("# 只有标题没有正文\n\n## 也没有\n")
        self.assertEqual(secs, [])


class TestChunkNote(unittest.TestCase):
    def test_frontmatter_separate_block(self):
        raw = f"---\ntitle: 测试\nupdated: 2026-08-01\n---\n# 正文\n{TestChunkMarkdown.BODY}"
        blocks = chunk_note("x.md", raw)
        self.assertEqual(blocks[0]["section"], "frontmatter")
        self.assertIn("title: 测试", blocks[0]["text"])
        self.assertEqual(blocks[1]["section"], "正文")

    def test_unterminated_frontmatter_is_body(self):
        raw = f"---\ntitle: 没有闭合\n{TestChunkMarkdown.BODY}"
        blocks = chunk_note("x.md", raw)
        self.assertTrue(all(b["section"] != "frontmatter" for b in blocks))

    def test_section_matches_prefix(self):
        raw = "# 父\n## 子\n" + "内容。" * 100
        for b in chunk_note("x.md", raw):
            self.assertEqual(b["text"].startswith(f"[{b['section']}]"),
                             b["section"] != "")


if __name__ == "__main__":
    unittest.main()
