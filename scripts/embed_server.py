# -*- coding: utf-8 -*-
"""用 llama-embedding.exe 提供 OpenAI 兼容的 embedding API。

用法：
    python embed_server.py --model models/Qwen/Qwen3-Embedding-8B/Qwen3-Embedding-8B-Q4_K_M.gguf --port 18765
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vault_rag.config import SUBPROCESS_FLAGS

def embed(texts: list[str], model: str, ctx_size: int = 512) -> list[list[float]]:
    """调用 llama-embedding.exe 生成向量。exe 路径经 LLAMA_EMBED_EXE 覆盖。"""
    exe = os.environ.get("LLAMA_EMBED_EXE", r"D:\llama.cpp\build\bin\llama-embedding.exe")
    if not Path(exe).exists():
        raise RuntimeError(f"llama-embedding.exe 不存在: {exe}")
    # llama-embedding 从 stdin 读取文本，每行一条
    input_text = "\n".join(texts)
    cmd = [
        exe,
        "-m", model,
        "--ctx-size", str(ctx_size),
        "--no-mmap",
        "--verbose",
    ]
    try:
        r = subprocess.run(cmd, input=input_text, capture_output=True, text=True,
                           timeout=300, creationflags=SUBPROCESS_FLAGS)
        if r.returncode != 0:
            raise RuntimeError(f"llama-embedding 失败: {r.stderr[:200]}")
        # 解析 JSON 输出
        results = []
        for line in r.stdout.strip().split("\n"):
            if line.startswith('{"object":"embedding"'):
                obj = json.loads(line)
                results.append(obj["embedding"])
        return results
    except Exception as e:
        raise RuntimeError(f"embedding 调用失败: {e}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", required=True, help="GGUF 模型路径")
    ap.add_argument("--test", help="测试嵌入")
    args = ap.parse_args()
    if args.test:
        vecs = embed([args.test], args.model)
        print(f"输入: {args.test}")
        print(f"维度: {len(vecs[0])}")
        print(f"前5维: {vecs[0][:5]}")
