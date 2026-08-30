# -*- coding: utf-8 -*-
"""config.py 环境变量覆盖测试（子进程重新 import，避免污染本进程）。"""
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


class TestConfigEnvOverride(unittest.TestCase):
    def _run(self, env: dict) -> str:
        code = (
            "import sys; sys.path.insert(0, r'%s');"
            "from vault_rag import config;"
            "print(config.DB_PATH);"
            "print(config.VAULT)" % REPO
        )
        e = {**os.environ, "PYTHONIOENCODING": "utf-8", **env}
        r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                           text=True, env=e, timeout=60)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout.strip().splitlines()

    def test_default_paths_are_repo_relative(self):
        db, vault = self._run({})
        self.assertEqual(Path(db).resolve().parent, (REPO / "data").resolve())

    def test_env_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            db, vault = self._run({
                "RAG_DATA_DIR": td,
                "VAULT_PATH": str(Path(td) / "vault"),
            })
            self.assertEqual(Path(db), Path(td) / "qwen_rag.db")

    def test_no_personal_username_in_sources(self):
        """开源卫生：仓库源码不得含机器用户名或硬编码个人路径（data/ 内部实验文件除外）。"""
        import re
        user = os.environ.get("USERNAME", "")
        offenders = []
        skip_parts = {"data", ".ragfiles", "models", "__pycache__", ".git", ".codex"}
        for p in REPO.rglob("*.py"):
            if skip_parts & set(p.parts):
                continue
            text = p.read_text(encoding="utf-8", errors="ignore")
            if user and user in text:
                offenders.append(f"{p}: username")
            if re.search(r"[A-F]:[\\/]+(AI Coding|测试)", text):
                offenders.append(f"{p}: personal path")
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
