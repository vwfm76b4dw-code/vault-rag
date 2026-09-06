# -*- coding: utf-8 -*-
"""嵌入模型切换/mmproj 配对的纯逻辑测试（不起真实 llama-server）。

背景实测事故：
1. 孤儿 llama-server 占住端口，stop_server 只杀自己子进程 → 切换模型永不生效；
2. mmproj 投影文件被当主模型启用 / 纯文本模型挂 VL 投影 → 必然加载失败。
"""
import struct
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vault_rag import embed_providers as ep


def _make_gguf(path: Path, arch: str) -> None:
    """构造仅含 general.architecture 键的最小 GGUF 头（gguf_arch 可解析）。"""
    key = arch.encode()
    with open(path, "wb") as f:
        f.write(b"GGUF")
        f.write(struct.pack("<IQQ", 3, 0, 1))          # version, n_tensors, n_kv
        f.write(struct.pack("<Q", len(key)) + key)      # key
        f.write(struct.pack("<I", 8))                   # value type = string
        f.write(struct.pack("<Q", len(key)) + key)      # value


class TestGgufIsVisual(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        _make_gguf(self.dir / "vl.gguf", "qwen3vl")
        _make_gguf(self.dir / "text.gguf", "qwen3")

    def tearDown(self):
        self.tmp.cleanup()

    def test_visual_by_arch(self):
        self.assertTrue(ep.gguf_is_visual(self.dir / "vl.gguf"))
        self.assertFalse(ep.gguf_is_visual(self.dir / "text.gguf"))

    def test_visual_fallback_by_name_when_arch_missing(self):
        # 头解析失败（非 GGUF 文件）→ 文件名兜底
        p = self.dir / "Qwen3-VL-2B.gguf"
        p.write_bytes(b"junk")
        self.assertTrue(ep.gguf_is_visual(p))
        p2 = self.dir / "plain.gguf"
        p2.write_bytes(b"junk")
        self.assertFalse(ep.gguf_is_visual(p2))

    def test_list_ggufs_carries_is_visual(self):
        old = ep.GGUF_DIR
        ep.GGUF_DIR = self.dir
        try:
            rows = {r["file"]: r for r in ep.list_ggufs()}
            self.assertTrue(rows["vl.gguf"]["is_visual"])
            self.assertFalse(rows["text.gguf"]["is_visual"])
        finally:
            ep.GGUF_DIR = old


class TestValidatePairing(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        _make_gguf(self.dir / "vl.gguf", "qwen3vl")
        _make_gguf(self.dir / "text.gguf", "qwen3")
        (self.dir / "mmproj-x.gguf").write_bytes(b"GGUF-junk")
        self.old_gguf_dir = ep.GGUF_DIR
        ep.GGUF_DIR = self.dir

    def tearDown(self):
        ep.GGUF_DIR = self.old_gguf_dir
        self.tmp.cleanup()

    def test_mmproj_as_main_rejected(self):
        with self.assertRaises(ValueError) as cm:
            ep.validate_pairing("mmproj-x.gguf", "")
        self.assertIn("视觉投影", str(cm.exception))

    def test_mmproj_on_text_model_rejected(self):
        with self.assertRaises(ValueError) as cm:
            ep.validate_pairing("text.gguf", "mmproj-x.gguf")
        self.assertIn("纯文本", str(cm.exception))

    def test_missing_files_reported(self):
        with self.assertRaises(FileNotFoundError):
            ep.validate_pairing("nope.gguf", "")
        with self.assertRaises(FileNotFoundError):
            ep.validate_pairing("vl.gguf", "no-mmproj.gguf")

    def test_valid_combinations_pass(self):
        ep.validate_pairing("text.gguf", "")              # 纯文本不带投影 ✓
        ep.validate_pairing("vl.gguf", "mmproj-x.gguf")   # 视觉主模型配投影 ✓
        ep.validate_pairing("vl.gguf", "")                # 视觉主模型不配投影 ✓


class TestPortOwnerParse(unittest.TestCase):
    def test_parse_listening_pids(self):
        fake = "\r\n".join([
            "  协议  本地地址          远程地址        状态           PID",
            "  TCP    127.0.0.1:18900       0.0.0.0:0              LISTENING       16636",
            "  TCP    127.0.0.1:18900       0.0.0.0:0              LISTENING       16636",
            "  TCP    127.0.0.1:8765        0.0.0.0:0              LISTENING       999",
            "  TCP    127.0.0.1:18901       1.2.3.4:5555           ESTABLISHED     777",
        ])
        with mock.patch.object(ep.subprocess, "run",
                               return_value=mock.Mock(stdout=fake)):
            self.assertEqual(ep._port_owner_pids(18900), [16636])

    def test_no_listener_returns_empty(self):
        with mock.patch.object(ep.subprocess, "run",
                               return_value=mock.Mock(stdout="")):
            self.assertEqual(ep._port_owner_pids(18900), [])


class TestServedModelMatch(unittest.TestCase):
    def setUp(self):
        self.gguf = Path(r"D:\x\data\gguf\a.gguf")

    def _fake_models_response(self, served_path):
        resp = mock.Mock()
        resp.json.return_value = {"models": [{"model": served_path}]}
        return resp

    def test_match_same_path(self):
        with mock.patch("requests.get", return_value=self._fake_models_response(str(self.gguf))):
            self.assertTrue(ep._served_model_matches(self.gguf))

    def test_mismatch_different_model(self):
        other = self.gguf.with_name("b.gguf")
        with mock.patch("requests.get", return_value=self._fake_models_response(str(other))):
            self.assertFalse(ep._served_model_matches(self.gguf))

    def test_endpoint_error_conservative_reuse(self):
        with mock.patch("requests.get", side_effect=RuntimeError("boom")):
            self.assertTrue(ep._served_model_matches(self.gguf))   # 读不到→保守复用


if __name__ == "__main__":
    unittest.main()
