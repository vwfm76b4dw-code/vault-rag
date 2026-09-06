# -*- coding: utf-8 -*-
"""沙盒集成实测：孤儿进程清场 + VL/mmproj 真切换。

模拟现场：18903 上有一个"别的实例起的" llama-server（旧 0.6B 模型，父进程非本脚本），
经 API 选择 VL 主模型 + mmproj 配对 → ensure_server() 必须杀掉孤儿并按新组合重启。
RAG_DATA_DIR / RAG_LLAMA_PORT 由外部环境变量传入（指向沙盒）。
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vault_rag import embed_providers as ep

PORT = ep.LLAMA_PORT
GGUF_DIR = ep.GGUF_DIR
VL_FILE = "Qwen.Qwen3-VL-Embedding-2B.Q8_0.gguf"
MMPROJ_FILE = "mmproj-Qwen.Qwen3-VL-Embedding-2B.f16.gguf"
TEXT_FILE = "Qwen3-Embedding-0.6B-Q8_0.gguf"
EXE = ep.resolve_llama_exe()          # 服务端探测链推导（红线：不硬编码个人路径）


def wait_health(timeout=60):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if ep.server_alive(0.5):
            return True
        time.sleep(0.5)
    return False


def main():
    # 1) 起一个"孤儿" llama-server（0.6B，无 --mmproj）——用独立进程模拟别的实例起的
    log = open(GGUF_DIR / "llama_server.log", "a", encoding="utf-8")
    orphan = subprocess.Popen(
        [str(EXE), "-m", str(GGUF_DIR / TEXT_FILE), "--embedding",
         "--host", "127.0.0.1", "--port", str(PORT)],
        stdout=log, stderr=log)
    assert wait_health(60), "孤儿 0.6B 服务未就绪"
    orphan_pid = ep._port_owner_pids(PORT)[0]
    print(f"[1] 孤儿 0.6B 就绪 pid={orphan_pid}")

    # 2) 经 API 选择 VL + mmproj（走真实 FastAPI 端点，含校验与 stop_server 清场）
    from fastapi.testclient import TestClient
    from vault_rag.webui import app
    with TestClient(app) as client:
        # 2a. 反向校验：mmproj 当主模型必须 422
        r = client.post("/api/embed/gguf/select", json={"file": MMPROJ_FILE, "mmproj": ""})
        assert r.status_code == 422, f"mmproj 当主模型应 422，实际 {r.status_code}"
        print("[2a] mmproj 当主模型 → 422 ✓")
        # 2b. 纯文本模型挂投影必须 422
        r = client.post("/api/embed/gguf/select",
                        json={"file": TEXT_FILE, "mmproj": MMPROJ_FILE})
        assert r.status_code == 422, f"文本模型挂投影应 422，实际 {r.status_code}"
        print("[2b] 0.6B 挂 VL 投影 → 422 ✓")
        # 2c. 正确组合
        r = client.post("/api/embed/gguf/select",
                        json={"file": VL_FILE, "mmproj": MMPROJ_FILE})
        assert r.status_code == 200, f"VL+mmproj 应 200，实际 {r.status_code}: {r.text[:200]}"
        body = r.json()
        print(f"[2c] VL+mmproj 选择成功 ✓ warning={body.get('warning', '')[:60]}")

    # 3) 孤儿已被按端口清场
    time.sleep(1.5)
    assert not ep.server_alive(0.5), "select 后孤儿仍占着端口（清场失败）"
    assert orphan_pid not in ep._port_owner_pids(PORT), "孤儿 PID 未被杀"
    print(f"[3] 孤儿 pid={orphan_pid} 已被清场 ✓")

    # 4) ensure_server → 按新组合（VL + mmproj）真重启
    port = ep.ensure_server(start_timeout=300)
    assert port == PORT
    assert wait_health(10)
    import requests
    served = requests.get(f"http://127.0.0.1:{PORT}/v1/models", timeout=5).json()
    served_name = Path(served["models"][0]["model"]).name
    assert served_name == VL_FILE, f"端口上服务的是 {served_name}，应为 {VL_FILE}"
    print(f"[4] ensure_server 后端口加载的是 VL 模型 ✓ ({served_name})")

    # 5) 文本嵌入维度（VL=2048）
    r = requests.post(f"http://127.0.0.1:{PORT}/v1/embeddings",
                      json={"input": "沙盒切换验证"}, timeout=60)
    dim = len(r.json()["data"][0]["embedding"])
    assert dim == 2048, f"应 2048 维，实际 {dim}"
    print(f"[5] VL 文本嵌入 2048 维 ✓")

    print("ALL PASS")


if __name__ == "__main__":
    try:
        main()
    finally:
        ep.stop_server(kill_port_owner=True)   # 沙盒清场：测试服务不留活口
