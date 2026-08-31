# -*- coding: utf-8 -*-
"""embed_providers.py — 内置 llama.cpp 向量后端 + HuggingFace GGUF 下载管理。

查询向量源优先级（可在 Web 设置面板调整）：
    HTTP 端点(LM Studio 等) → 内置 llama.cpp → 关键词检索
本地 torch 仅用于新增内容入索引（indexer_qwen），与此处无关。

llama.cpp 调用采用项目里已验证的 spawn 模式（embed_server.py 同款：
stdin 喂文本，stdout 解析 {"object":"embedding"...} 行），查询向量带
进程内缓存（同一问题秒回）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path

from vault_rag.config import BASE_DIR, DATA_DIR, SUBPROCESS_FLAGS

REPO = Path(__file__).resolve().parent
GGUF_DIR = DATA_DIR / "gguf"          # 跟随数据目录：exe 经 data_dir.txt 指针共用

_HF_BASE = {"hf": "https://huggingface.co", "mirror": "https://hf-mirror.com"}

# 预设：Qwen3 官方 GGUF（检索向量与库内 transformers 向量同源同池化）
HF_PRESETS = [
    {"repo": "Qwen/Qwen3-Embedding-0.6B-GGUF",
     "file": "Qwen3-Embedding-0.6B-Q8_0.gguf", "label": "Qwen3-Embedding 0.6B (Q8, 推荐)"},
    {"repo": "Qwen/Qwen3-Embedding-0.6B-GGUF",
     "file": "Qwen3-Embedding-0.6B-Q4_K_M.gguf", "label": "Qwen3-Embedding 0.6B (Q4, 更小)"},
]

_llama_cache: dict = {}
_LLAMA_CACHE_MAX = 512


def resolve_llama_exe() -> Path | None:
    """服务端探测链：环境变量 > 打包目录 llama/ > 仓库本地 llama/（官方预编译 llama-server）。"""
    for name in ("llama-server.exe", "llama-embedding.exe"):
        for p in [os.environ.get("RAG_LLAMA_EXE"),
                  BASE_DIR / "llama" / name,
                  REPO / "llama" / name]:
            if p and Path(p).exists():
                return Path(p)
    return None


def list_ggufs() -> list[dict]:
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(GGUF_DIR.glob("*.gguf"), key=lambda x: -x.stat().st_mtime):
        out.append({"file": p.name, "size_mb": round(p.stat().st_size / 1e6)})
    return out


def resolve_gguf() -> Path | None:
    """GGUF 探测链：环境变量 > 设置面板选定 > models/gguf 最新一个。"""
    from vault_rag import webui_lib
    chosen = webui_lib.load_local_settings().get("llama_gguf")
    if chosen and (GGUF_DIR / chosen).exists():
        return GGUF_DIR / chosen
    ggufs = list_ggufs()
    return (GGUF_DIR / ggufs[0]["file"]) if ggufs else None


def llama_available() -> dict:
    exe, gguf = resolve_llama_exe(), resolve_gguf()
    return {"exe": str(exe) if exe else "", "gguf": str(gguf.name) if gguf else "",
            "ready": bool(exe and gguf)}


def embed_llamacpp(text: str) -> list[float]:
    """单条文本 → 向量：托管本地 llama-server（常驻，首次启动加载模型 10~30s）。"""
    import numpy as np
    cached = _llama_cache.get(text)
    if cached is not None:
        return cached
    port = ensure_server()
    import requests
    r = requests.post(f"http://127.0.0.1:{port}/v1/embeddings",
                      json={"model": "qwen3", "input": [text]},
                      timeout=(5, 30))
    r.raise_for_status()
    vec = r.json()["data"][0]["embedding"]
    v = np.asarray(vec, dtype=np.float32)
    v = v / max(float(np.linalg.norm(v)), 1e-9)
    if len(_llama_cache) >= _LLAMA_CACHE_MAX:
        _llama_cache.clear()
    _llama_cache[text] = v.tolist()
    return _llama_cache[text]


# ---------- 内置 llama-server 托管 ----------

LLAMA_PORT = int(os.environ.get("RAG_LLAMA_PORT", "18900"))
_SERVER: dict = {"proc": None}


def server_alive(timeout: float = 1.5) -> bool:
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:{LLAMA_PORT}/health", timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def ensure_server(start_timeout: float = 90.0) -> int:
    """确保内置 llama-server 在跑（模型就绪），返回端口。"""
    if server_alive():
        return LLAMA_PORT
    if _SERVER["proc"] is not None and _SERVER["proc"].poll() is None:
        # 我们起的进程还在但没就绪 → 等健康
        t0 = time.time()
        while time.time() - t0 < start_timeout:
            if server_alive():
                return LLAMA_PORT
            time.sleep(1)
        raise RuntimeError("llama-server 启动超时（模型加载未完成）")

    exe, gguf = resolve_llama_exe(), resolve_gguf()
    if not exe or not gguf:
        raise RuntimeError(f"llama.cpp 不可用（exe={bool(exe)}, gguf={bool(gguf)}）")
    if exe.name != "llama-server.exe":
        raise RuntimeError(f"{exe.name} 不是 llama-server（新版官方构建用 llama-server --embedding）")
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    log = open(GGUF_DIR / "llama_server.log", "a", encoding="utf-8")
    flags = SUBPROCESS_FLAGS
    proc = subprocess.Popen(
        [str(exe), "-m", str(gguf), "--embedding", "--host", "127.0.0.1",
         "--port", str(LLAMA_PORT)],
        stdout=log, stderr=log, creationflags=flags)
    _SERVER["proc"] = proc
    t0 = time.time()
    while time.time() - t0 < start_timeout:
        if server_alive():
            return LLAMA_PORT
        if proc.poll() is not None:
            raise RuntimeError("llama-server 进程退出（详见 models/gguf/llama_server.log）")
        time.sleep(1)
    raise RuntimeError("llama-server 启动超时")


def stop_server():
    if _SERVER["proc"] is not None and _SERVER["proc"].poll() is None:
        _SERVER["proc"].terminate()
    _SERVER["proc"] = None


import atexit
atexit.register(stop_server)


# ---------- HF GGUF 下载（断点续传 + 进度） ----------

_DL: dict = {"running": False, "file": "", "downloaded": 0, "total": 0,
             "pct": 0.0, "done": False, "error": "", "t0": 0.0}


def hf_base(mirror: bool) -> str:
    return _HF_BASE["mirror"] if mirror else _HF_BASE["hf"]


def hf_list_files(repo: str, mirror: bool = True, timeout: float = 20) -> list[dict]:
    """列出仓库内 GGUF 文件（走 HF API，镜像同路径）。"""
    import requests
    base = hf_base(mirror)
    r = requests.get(f"{base}/api/models/{repo}/tree/main", timeout=timeout)
    r.raise_for_status()
    out = []
    for it in r.json():
        name = it.get("path", "")
        if name.lower().endswith(".gguf"):
            out.append({"file": name, "size_mb": round(it.get("size", 0) / 1e6)})
    return out


def dl_status() -> dict:
    s = dict(_DL)
    if s["running"] and s["t0"]:
        s["speed_mbs"] = round(s["downloaded"] / max(1e-6, time.time() - s["t0"]) / 1e6, 1)
    return s


def hf_download(repo: str, file: str, mirror: bool = True) -> dict:
    """后台线程断点续传下载 GGUF → models/gguf/。"""
    if _DL["running"]:
        return {"ok": False, "message": "已有下载在进行中"}
    dest = GGUF_DIR / file
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    url = f"{hf_base(mirror)}/{repo}/resolve/main/{file}"

    def worker():
        import requests
        _DL.update({"running": True, "file": file, "done": False, "error": "",
                    "t0": time.time(), "pct": 0.0})
        try:
            pos = dest.stat().st_size if dest.exists() else 0
            headers = {"Range": f"bytes={pos}-"} if pos else {}
            with requests.get(url, stream=True, timeout=(15, 60), headers=headers) as r:
                if r.status_code == 416:
                    _DL.update({"done": True, "pct": 100.0})   # 文件已完整（越界续传被拒）
                    return {"ok": True, "message": "文件已完整，无需下载"}
                if r.status_code not in (200, 206):
                    raise RuntimeError(f"HTTP {r.status_code}")
                total = int(r.headers.get("content-length", 0)) + pos
                _DL["total"] = total
                with open(dest, "ab" if pos else "wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
                        pos += len(chunk)
                        _DL["downloaded"] = pos
                        _DL["pct"] = round(pos / total * 100, 1) if total else 0
            _DL["done"] = True
        except Exception as e:
            _DL["error"] = f"{type(e).__name__}: {e}"
        finally:
            _DL["running"] = False

    threading.Thread(target=worker, name="hf-download", daemon=True).start()
    return {"ok": True, "message": f"开始下载 {file}"}
