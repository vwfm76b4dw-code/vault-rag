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
        out.append({"file": p.name, "is_mmproj": "mmproj" in p.name.lower(),
                    "is_visual": gguf_is_visual(p),
                    "arch": gguf_arch(p), "size_mb": round(p.stat().st_size / 1e6)})
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


def _served_model_matches(gguf: Path) -> bool:
    """端口上的 llama-server 是否正加载配置指定的模型（/v1/models 读回启动模型路径）。

    读不到（端点异常/老版本无此路由）时保守返回 True，避免误杀健康服务。
    """
    try:
        import requests
        r = requests.get(f"http://127.0.0.1:{LLAMA_PORT}/v1/models", timeout=2)
        served = ((r.json().get("models") or [{}])[0].get("model") or "")
    except Exception:
        return True
    try:
        return Path(served).resolve() == gguf.resolve()
    except Exception:
        return Path(served).name == gguf.name


def _server_log_tail(n: int = 400) -> str:
    """llama_server.log 末段——启动失败时直接附进异常消息，用户不用翻日志文件。"""
    try:
        return (GGUF_DIR / "llama_server.log").read_text(encoding="utf-8", errors="replace")[-n:]
    except Exception:
        return ""


def ensure_server(start_timeout: float = 240.0) -> int:
    """确保内置 llama-server 在跑（模型就绪），返回端口。

    默认 240s：实测 VL 1.8G + mmproj 800M 冷加载 ~100s，90s 会超时误报。
    """
    if server_alive():
        # 探活命中还不够：端口上的活服务可能是其它实例/历史遗留按旧模型起的
        # 孤儿进程（实测事故：父进程已死，stop_server 永远杀不到，"切换模型"
        # 看似成功实则永远用旧模型）。服务模型与配置不符时必须清场重启。
        gguf_now = resolve_gguf()
        if gguf_now is None or _served_model_matches(gguf_now):
            return LLAMA_PORT
        stop_server()
        time.sleep(0.5)
    if _SERVER["proc"] is not None and _SERVER["proc"].poll() is None:
        # 我们起的进程还在但没就绪 → 等健康
        t0 = time.time()
        while time.time() - t0 < start_timeout:
            if server_alive():
                return LLAMA_PORT
            time.sleep(1)
        raise RuntimeError("llama-server 启动超时（模型加载未完成）——日志末段：" + _server_log_tail())

    exe, gguf = resolve_llama_exe(), resolve_gguf()
    if not exe or not gguf:
        raise RuntimeError(f"llama.cpp 不可用（exe={bool(exe)}, gguf={bool(gguf)}）")
    if exe.name != "llama-server.exe":
        raise RuntimeError(f"{exe.name} 不是 llama-server（新版官方构建用 llama-server --embedding）")
    GGUF_DIR.mkdir(parents=True, exist_ok=True)
    log = open(GGUF_DIR / "llama_server.log", "a", encoding="utf-8")
    flags = SUBPROCESS_FLAGS
    cmd = [str(exe), "-m", str(gguf), "--embedding", "--pooling", "last",
           "--host", "127.0.0.1", "--port", str(LLAMA_PORT)]
    # --pooling last：部分 GGUF（如 VL 系）元数据未声明 pooling，/v1/embeddings 会 400
    # 493c92d 曾在此裸调用 load_local_settings() → NameError，凡需真正重启服务的
    # 场景（换模型/服务掉线）必崩，检索静默降级关键词——必须走 webui_lib 前缀
    from vault_rag import webui_lib
    mmproj = webui_lib.load_local_settings().get("llama_mmproj")
    # 配置里可能残留与主模型错配的 mmproj（实测 0.6B 挂 VL 投影必然加载失败）——
    # 非视觉主模型一律忽略该配置，防止启动即崩
    if mmproj and gguf_is_visual(gguf) and (GGUF_DIR / mmproj).exists():
        cmd += ["--mmproj", str(GGUF_DIR / mmproj)]   # 视觉投影（用户配置）
    proc = subprocess.Popen(
        cmd, stdout=log, stderr=log, creationflags=flags)
    _SERVER["proc"] = proc
    t0 = time.time()
    while time.time() - t0 < start_timeout:
        if server_alive():
            return LLAMA_PORT
        if proc.poll() is not None:
            raise RuntimeError("llama-server 进程退出——日志末段：" + _server_log_tail())
        time.sleep(1)
    raise RuntimeError("llama-server 启动超时——日志末段：" + _server_log_tail())


def _port_owner_pids(port: int) -> list[int]:
    """找到监听该端口的进程 PID（netstat 解析，无第三方依赖）。"""
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"],
                             capture_output=True, text=True, timeout=10).stdout
    except Exception:
        return []
    pids = []
    for ln in out.splitlines():
        parts = ln.split()
        if len(parts) >= 5 and parts[3] == "LISTENING" and parts[1].endswith(f":{port}"):
            if parts[4].isdigit() and parts[4] not in pids:
                pids.append(parts[4])
    return [int(p) for p in pids]


def _kill_port_owner(port: int) -> None:
    """按端口清场：杀掉占用端口的 llama-server（不论父进程是谁）。

    端口被非 llama-server 进程占用时不动手（防御误杀无关服务）。
    """
    for pid in _port_owner_pids(port):
        name = ""
        try:
            out = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/FO", "CSV", "/NH"],
                                 capture_output=True, text=True, timeout=10).stdout
            if '"' in out:
                name = out.split('"')[1].lower()
        except Exception:
            pass
        if name and "llama-server" not in name and "llama-embedding" not in name:
            continue
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                       capture_output=True, text=True, timeout=10)


def stop_server(kill_port_owner: bool = True):
    """停掉托管 llama-server 并清空查询缓存。

    terminate() 只对本进程的子进程有效；其它实例/历史遗留的 llama-server 仍会
    占着端口，之后探活复用会让"切换模型"永不生效——所以切换/重启用按端口清场
    （kill_port_owner=True）。应用退出钩子传 False，只收自己的子进程，
    不动其它实例正在共享的服务。
    """
    if _SERVER["proc"] is not None and _SERVER["proc"].poll() is None:
        _SERVER["proc"].terminate()
    _SERVER["proc"] = None
    _llama_cache.clear()          # 换模型后旧向量必须作废（查询侧进程内缓存）
    if kill_port_owner:
        _kill_port_owner(LLAMA_PORT)
        t0 = time.time()
        while server_alive(0.5) and time.time() - t0 < 10:
            time.sleep(0.3)


def gguf_arch(path) -> str | None:
    """读 GGUF 头部的 general.architecture（不依赖第三方库；失败返回 None）。"""
    try:
        import struct
        with open(path, "rb") as f:
            magic = f.read(4)
            if magic != b"GGUF":
                return None
            ver, n_tensors, n_kv = struct.unpack("<IQQ", f.read(20))
            if ver < 2:
                return None

            def _rd_str():
                n = struct.unpack("<Q", f.read(8))[0]
                return f.read(n).decode("utf-8", "replace")

            def _rd_val(vt):
                if vt == 8:
                    return _rd_str()
                if vt == 4:
                    return struct.unpack("<I", f.read(4))[0]
                if vt == 5:
                    return struct.unpack("<i", f.read(4))[0]
                if vt == 6:
                    return struct.unpack("<f", f.read(4))[0]
                if vt == 7:
                    return struct.unpack("<B", f.read(1))[0]
                if vt == 10:
                    return struct.unpack("<Q", f.read(8))[0]
                if vt == 9:
                    return struct.unpack("<q", f.read(8))[0]
                if vt == 0:
                    return struct.unpack("<B", f.read(1))[0]
                return None  # 数组等复杂类型跳过（当前键序用不到）

            for _ in range(min(n_kv, 64)):
                key = _rd_str()
                vt = struct.unpack("<I", f.read(4))[0]
                val = _rd_val(vt)
                if key == "general.architecture":
                    return str(val)
        return None
    except Exception:
        return None


VISUAL_ARCH_MARKERS = ("vl", "vision", "mmproj", "clip")


def gguf_is_visual(path) -> bool:
    """GGUF 是否含视觉塔（架构头判定；头解析失败时按文件名兜底）。"""
    arch = (gguf_arch(path) or "").lower()
    if arch:
        return any(m in arch for m in VISUAL_ARCH_MARKERS)
    name = Path(path).name.lower()
    return "vl" in name or "vision" in name


def gguf_visual_warning(path) -> str:
    """视觉模型 GGUF 选择提示（llama-server 文本嵌入未支持视觉塔）。"""
    arch = gguf_arch(path) or ""
    if any(m in arch.lower() for m in VISUAL_ARCH_MARKERS):
        return (f"该 GGUF 架构为 {arch}（含视觉塔）——llama-server 的文本嵌入接口"
                f"大概率不支持，切换后检索会失败。VL 视觉索引请走本地 torch 路径"
                f"（多模态管线已内置）。")
    return ""


def validate_pairing(file: str, mmproj: str = "") -> None:
    """主模型 / mmproj 组合校验，不合法抛 ValueError（消息可直接给用户）。

    防两种实测出错的组合：mmproj 投影文件被当主模型启用；
    纯文本嵌入模型挂视觉投影（0.6B + VL mmproj 必然加载失败）。
    """
    if "mmproj" in file.lower():
        raise ValueError("mmproj 是视觉投影文件，不能作为嵌入主模型——"
                         "请在列表选择主模型（VL 模型），再在详情面板配对 mmproj")
    main = GGUF_DIR / file
    if not main.exists():
        raise FileNotFoundError(f"文件不存在: {file}")
    if mmproj:
        if not (GGUF_DIR / mmproj).exists():
            raise FileNotFoundError(f"mmproj 文件不存在: {mmproj}")
        if not gguf_is_visual(main):
            raise ValueError(f"{file} 是纯文本嵌入模型，不需要配对 mmproj；"
                             f"视觉投影仅用于 VL 等视觉塔模型（先选 VL 主模型再配对）")


import atexit
atexit.register(lambda: stop_server(kill_port_owner=False))   # 退出只收自己的子进程，不动共享服务


# ---------- HF GGUF 下载（断点续传 + 进度） ----------

_DL: dict = {"running": False, "file": "", "downloaded": 0, "total": 0,
             "pct": 0.0, "done": False, "error": "", "t0": 0.0}


def hf_base(mirror: bool) -> str:
    return _HF_BASE["mirror"] if mirror else _HF_BASE["hf"]


def hf_list_files(repo: str, mirror: bool = True, timeout: float = 20) -> list[dict]:
    """列出仓库内 GGUF 文件（走 HF API，镜像同路径）。

    错误人性化：HF 对「不存在/私有」仓库统一返回 401（防枚举），
    原样透传会让用户以为是鉴权问题。
    """
    import requests
    base = hf_base(mirror)
    r = requests.get(f"{base}/api/models/{repo}/tree/main", timeout=timeout)
    if r.status_code in (401, 403, 404):
        hint = ""
        low = repo.lower()
        if "vl-embedding-2b-fp8" in low or "vl-embedding-2b-awq" in low:
            hint = ("提示：Qwen3-VL-Embedding-2B 的 FP8/AWQ 是 transformers 权重仓库"
                    "（safetensors，无 GGUF），供本地 torch 路径使用（本机已内置）；"
                    "GGUF 版社区仓库如 jfiekdjdk/Qwen3-VL-Embedding-2B-Q8_0-GGUF，"
                    "但 llama-server 对视觉嵌入的支持未经验证。")
        raise RuntimeError(
            f"仓库「{repo}」不存在或未公开（HF 对不存在/私有仓库统一返回 401）。"
            f"请检查仓库 id 拼写，或用关键词搜索。{hint}")
    r.raise_for_status()
    out = []
    for it in r.json():
        name = it.get("path", "")
        if name.lower().endswith(".gguf"):
            out.append({"file": name, "size_mb": round(it.get("size", 0) / 1e6)})
    if not out:
        raise RuntimeError(
            f"仓库「{repo}」里没有 GGUF 文件——它可能是 transformers/safetensors 权重仓库，"
            f"不适用于内置 llama.cpp（GGUF 下载器）。")
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
