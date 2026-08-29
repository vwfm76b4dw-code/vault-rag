# -*- coding: utf-8 -*-
"""freshness.py 单元测试：S1/S2/S3 信号提取、簇裁决、簇类型学。

含回归：无 updated 字段时 declared_updated 必须为 None（旧版解析出字符串
"None"，字典序大于任何真实日期，导致权威裁决反向）。
"""
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from freshness import Freshness, cluster_kind, cluster_of, extract_signals, rank_cluster


def _mk(td: Path, name: str, content: str) -> tuple[Path, str]:
    p = Path(td) / name
    p.write_text(content, encoding="utf-8")
    return p, name


class TestExtractSignals(unittest.TestCase):
    def test_declared_updated_regression_none_bug(self):
        """旧版：str(fm.get('updated'))[:10] → 'None'，排序权重反超真日期。"""
        with tempfile.TemporaryDirectory() as td:
            p, name = _mk(Path(td), "笔记A.md", "---\ntitle: x\n---\n正文")
            m = extract_signals(p, name)
            self.assertIsNone(m.declared_updated)
            self.assertEqual(m.authority_rank, (1, "0000"))

    def test_declared_updated_present(self):
        with tempfile.TemporaryDirectory() as td:
            p, name = _mk(Path(td), "笔记A.md",
                          "---\nupdated: 2026-08-01 12:00\n---\n正文")
            m = extract_signals(p, name)
            self.assertEqual(m.declared_updated, "2026-08-01")

    def test_date_priority_name_over_fm_over_body(self):
        with tempfile.TemporaryDirectory() as td:
            p, name = _mk(Path(td), "早报-2026-08-20.md",
                          "---\ndate: 2026-07-01\n---\n提到 2026-06-01 的事")
            self.assertEqual(extract_signals(p, name).embedded_date, "2026-08-20")
            p2, name2 = _mk(Path(td), "无日期.md",
                            "---\ndate: 2026-07-01\n---\n提到 2026-06-01 的事")
            self.assertEqual(extract_signals(p2, name2).embedded_date, "2026-07-01")
            p3, name3 = _mk(Path(td), "无日期.md", "正文提到 2026-06-01 的事")
            self.assertEqual(extract_signals(p3, name3).embedded_date, "2026-06-01")

    def test_superseded_and_history_mark(self):
        with tempfile.TemporaryDirectory() as td:
            p, name = _mk(Path(td), "旧文档.md",
                          "---\nsuperseded_by: 新文档.md\n---\n这是历史版本存档")
            m = extract_signals(p, name)
            self.assertEqual(m.superseded_by, "新文档.md")
            self.assertTrue(m.has_history_mark)
            self.assertEqual(m.authority_rank[0], 0)      # 直接沉底


class TestRankCluster(unittest.TestCase):
    def _m(self, rel, size, **kw):
        return Freshness(rel_path=rel, size=size, **kw)

    def test_size_cliff_marks_stale(self):
        ms = [self._m("大.md", 50000), self._m("小.md", 5000)]
        w, stale = rank_cluster(ms)
        self.assertEqual(w, "大.md")
        self.assertEqual(stale, ["小.md"])

    def test_explicit_supersede_wins_over_size(self):
        ms = [self._m("小但新.md", 5000, declared_updated="2026-08-01"),
              self._m("大但旧.md", 50000, superseded_by="小但新.md")]
        w, stale = rank_cluster(ms)
        self.assertEqual(w, "小但新.md")
        self.assertEqual(stale, ["大但旧.md"])

    def test_newest_date_authoritative(self):
        ms = [self._m("a.md", 100, declared_updated="2026-01-01"),
              self._m("b.md", 100, declared_updated="2026-08-01")]
        w, stale = rank_cluster(ms)
        self.assertEqual(w, "b.md")
        self.assertEqual(stale, [])


class TestClusterKind(unittest.TestCase):
    def _m(self, rel, size=1000, **kw):
        return Freshness(rel_path=rel, size=size, **kw)

    def test_temporal_series(self):
        ms = [self._m("早报-2026-08-01.md"), self._m("早报-2026-08-02.md"),
              self._m("早报-2026-08-03.md")]
        self.assertEqual(cluster_kind(ms), "temporal_series")

    def test_version_by_history_mark(self):
        ms = [self._m("设计.md"), self._m("设计-旧.md", has_history_mark=True)]
        self.assertEqual(cluster_kind(ms), "version")

    def test_mixed(self):
        ms = [self._m("甲.md"), self._m("乙.md")]
        self.assertEqual(cluster_kind(ms), "mixed")


class TestClusterOf(unittest.TestCase):
    def test_strips_date_and_prefix(self):
        self.assertEqual(cluster_of("研究/2026-08-05-早报.md"), "早报.md".replace(".md", ""))
        self.assertEqual(cluster_of("x/03-设计文档.md"), "设计文档")


if __name__ == "__main__":
    unittest.main()
