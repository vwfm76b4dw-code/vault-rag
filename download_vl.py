# -*- coding: utf-8 -*-
"""断点续传下载 Qwen3-VL-Embedding-2B（hf-mirror，可反复重跑续传）。"""
import time
from pathlib import Path
import requests

S = "https://hf-mirror.com"
BASE = f"{S}/Qwen/Qwen3-VL-Embedding-2B/resolve/main"
FILES = ["model.safetensors", "config.json", "tokenizer_config.json",
         "tokenizer.json", "preprocessor_config.json", "generation_config.json",
         "chat_template.json", "merges.txt", "vocab.json"]
OUT = Path("models/Qwen3-VL-Embedding-2B")
OUT.mkdir(parents=True, exist_ok=True)

for name in FILES:
    dest = OUT / name
    pos = dest.stat().st_size if dest.exists() else 0
    try:
        expect = int(requests.head(f"{BASE}/{name}", allow_redirects=True, timeout=60)
                     .headers.get("content-length", 0))
    except Exception:
        expect = 0
    if expect and pos >= expect:
        print(f"[skip] {name} 已完整", flush=True)
        continue
    headers = {"Range": f"bytes={pos}-"} if pos else {}
    with requests.get(f"{BASE}/{name}", stream=True, timeout=120, headers=headers) as r:
        if r.status_code not in (200, 206):
            print(f"[fail] {name} HTTP {r.status_code}", flush=True)
            continue
        total = pos + int(r.headers.get("content-length", 0))
        with open(dest, "ab" if pos else "wb") as f:
            for chunk in r.iter_content(4 << 20):
                f.write(chunk)
                pos += len(chunk)
        mode = "续传完成" if expect else "完成"
        print(f"[{mode}] {name} {pos/1e6:.0f}MB", flush=True)
print("ALL DONE", flush=True)
