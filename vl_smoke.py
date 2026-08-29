# -*- coding: utf-8 -*-
"""Qwen3-VL-Embedding-2B 冒烟测试：bf16 CPU + MRL 截断到 1024。
用法：python vl_smoke.py   （下载完成后运行）
"""
import os, sys, time
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, ".")

import numpy as np
import torch

torch.set_num_threads(10)   # 用户线程配额

from vl_embedder import Qwen3VLEmbedder

MODEL_DIR = "models/Qwen3-VL-Embedding-2B"

print("加载 VL embedder (bf16, CPU)...", flush=True)
t0 = time.time()
emb = Qwen3VLEmbedder(model_name_or_path=MODEL_DIR, torch_dtype=torch.bfloat16)
print(f"loaded in {time.time()-t0:.0f}s", flush=True)

texts = [
    "π 的前 100 万位数字序列文件",
    "一张日落海滩上女子与金毛犬互动的照片",
]
t0 = time.time()
vectors = emb.process([{"text": t} for t in texts]).float()
dt = time.time() - t0
v = vectors.cpu().numpy().astype(np.float32)
print(f"文本编码: {dt:.1f}s | shape={v.shape}")
norms = np.linalg.norm(v, axis=1)
print(f"L2 范数: {norms}")

# MRL 截断到 1024 并重新归一化（与文本库同维共存的关键验证）
trunc = v[:, :1024]
trunc = trunc / np.maximum(np.linalg.norm(trunc, axis=1, keepdims=True), 1e-9)
sim_matrix = trunc @ trunc.T
print(f"MRL→1024 截断 OK，自相似度矩阵:\n{sim_matrix}")

# 图像编码冒烟（从本仓库 data/ppt_imgs 取一张现成图，无则跳过）
img_path = None
imgs_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "ppt_imgs")
if os.path.isdir(imgs_dir):
    for name in sorted(os.listdir(imgs_dir)):
        if name.lower().endswith((".png", ".jpg", ".jpeg")):
            img_path = os.path.join(imgs_dir, name)
            break
if img_path:
    t0 = time.time()
    vi = emb.process([{"image": img_path}]).float().cpu().numpy().astype(np.float32)
    print(f"图像编码: {time.time()-t0:.1f}s | dim={vi.shape[1]}")
    # 图文跨模态一致性粗检
    vt = v[1] / np.linalg.norm(v[1])
    vii = vi[0][:vt.shape[0]] / max(np.linalg.norm(vi[0][:vt.shape[0]]), 1e-9)
    print(f"文本『海滩女子与狗』 vs 该图的余弦: {float(vt @ vii):.3f}")
else:
    print("(data/ppt_imgs 下无测试图片，跳过图像项)")
