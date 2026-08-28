# -*- coding: utf-8 -*-
"""VL embedder fp32 补丁：bf16 视觉塔数值下溢 → MRL 截断失效的修复。
用法：from vl_embed_fp32 import load_vl; emb = load_vl()"""
import os, sys
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import torch
torch.set_num_threads(10)
from vl_embedder import Qwen3VLEmbedder

def load_vl():
    return Qwen3VLEmbedder(model_name_or_path="models/Qwen3-VL-Embedding-2B",
                           torch_dtype=torch.float32)   # ← 关键：fp32 防视觉塔下溢

def enc_mrl(emb, x, dim=1024):
    v = emb.process([x]).float().cpu().numpy().reshape(-1)
    v = v[:dim]
    return v / max(float((v ** 2).sum() ** 0.5), 1e-9)
