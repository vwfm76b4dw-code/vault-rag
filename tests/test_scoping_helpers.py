# -*- coding: utf-8 -*-
"""git_diff_scope 自举 + stop_hook 并发锁测试（路径全部指向临时目录）。"""
import sys
import tempfile
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))


class TestGitDiffScopeBootstrap(unittest.TestCase):
    def setUp(self):
        import git_diff_scope as g
        self.g = g
        self._tmp = tempfile.TemporaryDirectory()
        g.REPO = Path(self._tmp.name) / ".ragfiles"

    def tearDown(self):
        self._tmp.cleanup()

    def test_ensure_creates_repo_and_baseline(self):
        """回归：旧版全新环境 ensure_tracking_repo 是死代码，changed 直接抛异常。"""
        self.assertTrue(self.g.ensure_tracking_repo())      # 首次：建立
        self.assertFalse(self.g.ensure_tracking_repo())     # 二次：幂等
        self.assertTrue((self.g.REPO / ".git").exists())
        self.assertTrue(self.g.latest_baseline().startswith("rag-baseline-"))

    def test_changed_files_detects_modification(self):
        with tempfile.TemporaryDirectory() as vd:
            vault_md = Path(vd) / "note.md"
            vault_md.write_text("v1", encoding="utf-8")

            def snap():                       # 模拟真实 snapshot：文件消失则不计入
                try:
                    mt = vault_md.stat().st_mtime
                except OSError:
                    return {}
                return {"vault/note.md": (vault_md, mt)}

            orig = self.g.snapshot_files
            self.g.snapshot_files = snap
            try:
                self.g.ensure_tracking_repo()
                time.sleep(0.7)                           # 变更检测阈值为 0.5s
                vault_md.write_text("v2", encoding="utf-8")   # 变更
                mods, dels = self.g.changed_files()
                self.assertEqual([k for k, _ in mods], ["vault/note.md"])
                self.assertEqual(dels, [])
                vault_md.unlink()
                _, dels = self.g.changed_files()
                self.assertEqual(dels, ["vault/note.md"])
            finally:
                self.g.snapshot_files = orig


class TestStopHookLock(unittest.TestCase):
    def setUp(self):
        import stop_hook as s
        self.s = s
        self._tmp = tempfile.TemporaryDirectory()
        s.LOCK = Path(self._tmp.name) / "index_running.lock"

    def tearDown(self):
        self._tmp.cleanup()

    def test_atomic_acquire(self):
        self.assertTrue(self.s.acquire_lock())
        self.assertFalse(self.s.acquire_lock())     # 第二次必须失败（O_EXCL）

    def test_stale_lock_broken_after_timeout(self):
        self.assertTrue(self.s.acquire_lock())
        old = time.time() - self.s.LOCK_STALE_SECONDS - 10
        import os
        os.utime(self.s.LOCK, (old, old))
        self.assertTrue(self.s.acquire_lock())      # 死锁超时 → 清理重试成功

    def test_short_circuit_no_changes(self):
        """mtime 短路：信号新于 vault → 不触发、不写日志。"""
        s = self.s
        orig_vault = s.VAULT
        orig_signal = s.SIGNAL
        try:
            with tempfile.TemporaryDirectory() as vd:
                s.VAULT = Path(vd)
                (s.VAULT / "a.md").write_text("x", encoding="utf-8")
                sig = Path(vd) / "sig"
                sig.write_text(f"{time.time() + 999:.6f}", encoding="utf-8")
                s.SIGNAL = sig
                self.assertEqual(s.main(), 0)
                self.assertFalse(s.LOCK.exists())   # 未触发、未上锁
        finally:
            s.VAULT = orig_vault
            s.SIGNAL = orig_signal


if __name__ == "__main__":
    unittest.main()
