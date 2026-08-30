# -*- coding: utf-8 -*-
"""图像纹理复杂度判定：局部方差 + 色彩丰富度双特征。

v1 教训（2026-08-28）：Sobel+高频占比在暗场景照片上饱和失真
（月亮火箭图 hf≈1.0 被误判复杂）。改用感知相关特征并校准阈值。
路由用途：低纹理→本地 VL-FP8 嵌入；高纹理→云端 VLM 中文描述。
"""
import numpy as np
from PIL import Image

def texture_score(image_path: str) -> float:
    im = Image.open(image_path).convert("RGB")
    im.thumbnail((512, 512))
    a = np.asarray(im, dtype=np.float32)
    gray = a.mean(axis=2)
    # 特征1：局部方差均值（真实细节 vs 平色块），归一到 ~[0,1]
    k = 8
    lv = _local_var(gray, k)
    # 特征2：色彩多样性（量化直方图非零 bin 占比）
    q = (a.astype(np.uint8) >> 4)
    codes = (q[..., 0].astype(np.int32) << 8 | q[..., 1].astype(np.int32) << 4 | q[..., 2].astype(np.int32))
    color_rich = len(np.unique(codes)) / 4096
    score = min(1.0, float(lv) / 1500 * 0.7 + color_rich * 0.6)
    return round(score, 3)

def _local_var(g, k):
    from numpy.lib.stride_tricks import sliding_window_view
    v = sliding_window_view(g, (k, k)).var(axis=(-1, -2))
    return float(v.mean())

def route(image_path: str, threshold: float = 0.35) -> str:
    """cloud=需云端 VLM 描述；local=本地 FP8 嵌入即可"""
    return "cloud" if texture_score(image_path) >= threshold else "local"
