# -*- coding: utf-8 -*-
"""断点续传下载 Qwen3-VL-Embedding-2B-AWQ-4bit（含 chat_template 从 instruct 补）"""
import time
from pathlib import Path
import requests

S = "https://hf-mirror.com"
SRC = f"{S}/LifetimeMistake/Qwen3-VL-Embedding-2B-AWQ-4bit/resolve/main"
OUT = Path("models/Qwen3-VL-Embedding-2B-AWQ-4bit")
OUT.mkdir(parents=True, exist_ok=True)

FILES = ["model.safetensors", "config.json", "tokenizer_config.json", "tokenizer.json",
         "preprocessor_config.json", "generation_config.json", "merges.txt", "vocab.json",
         "special_tokens_map.json", "added_tokens.json", "video_preprocessor_config.json"]

for name in FILES:
    dest = OUT / name
    pos = dest.stat().st_size if dest.exists() else 0
    try:
        head = requests.head(f"{SRC}/{name}", allow_redirects=True, timeout=60)
        expect = int(head.headers.get("content-length", 0))
    except Exception:
        expect = 0
    if expect and pos >= expect:
        print(f"[skip] {name}", flush=True); continue
    headers = {"Range": f"bytes={pos}-"} if pos else {}
    with requests.get(f"{SRC}/{name}", stream=True, timeout=180, headers=headers) as r:
        if r.status_code not in (200, 206):
            print(f"[fail] {name} HTTP {r.status_code}", flush=True); continue
        with open(dest, "ab" if pos else "wb") as f:
            for chunk in r.iter_content(4 << 20):
                f.write(chunk); pos += len(chunk)
    print(f"[done] {name} {pos/1e6:.0f}MB", flush=True)

# chat template 官方仓库没有，从 base instruct 注入（已验证可用）
ct = OUT / "chat_template.json"
if not ct.exists():
    r = requests.get(f"{S}/Qwen/Qwen3-VL-2B-Instruct/raw/main/chat_template.json", timeout=60)
    if r.ok:
        ct.write_bytes(r.content)
        print("[inject] chat_template from Qwen3-VL-2B-Instruct", flush=True)
print("ALL DONE", flush=True)
