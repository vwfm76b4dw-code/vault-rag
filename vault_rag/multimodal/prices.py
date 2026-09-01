# -*- coding: utf-8 -*-
"""prices.py — 视觉模型价格表（来源 models.dev，与 cc-switch 价格面板同源）。

拉全量目录缓存 7 天，抽取已知国内供应商的视觉模型单价（$/M tokens）。
估算口径：一页图 ≈ 1100 输入 token + 350 输出 token。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from vault_rag.config import DATA_DIR

CACHE = DATA_DIR / "_modelsdev_cache.json"
CACHE_TTL = 7 * 86400
PROVIDERS = ("agnes", "zhipu", "siliconflow", "dashscope", "deepseek")
PAGE_IN_TOK, PAGE_OUT_TOK = 1100, 350

# 兜底表（models.dev 拉不到时也能估算；与 2026-09-01 快照一致）
def _fm(i, o, name):
    # 兜底目录条目与 models.dev 结构一致（modalities 标记图像输入）
    return {"cost": {"input": i, "output": o}, "name": name,
            "modalities": {"input": ["text", "image"], "output": ["text"]}}


_FALLBACK = {
    "agnes": {"agnes-2.5-flash": _fm(0.0, 0.0, "Agnes 2.5 Flash"),
              "agnes-2.0-flash": _fm(0.0, 0.0, "Agnes 2.0 Flash"),
              "agnes-2.5-pro-alpha": _fm(0.45, 0.9, "Agnes 2.5 Pro Alpha")},
    "siliconflow": {"Qwen/Qwen3-VL-8B-Instruct": _fm(0.18, 0.68, "Qwen3-VL-8B")},
    "deepseek": {"deepseek-v4-flash-vision-exp": _fm(0.14, 0.28, "DeepSeek V4 Flash Vision")},
}


def _fetch() -> dict | None:
    import urllib.request
    try:
        with urllib.request.urlopen("https://models.dev/api.json", timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def catalog(force: bool = False) -> dict:
    if not force and CACHE.exists():
        try:
            c = json.loads(CACHE.read_text(encoding="utf-8"))
            if time.time() - c.get("_ts", 0) < CACHE_TTL:
                return c["data"]
        except Exception:
            pass
    data = _fetch()
    if data is None:
        return {"_fallback": True,
                **{k: {"models": dict(vs)} for k, vs in _FALLBACK.items()}}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"_ts": time.time(), "data": data}), encoding="utf-8")
    return data


def vision_models() -> list[dict]:
    """国内已知供应商的视觉模型 [{provider, model, in, out, free, name}]。"""
    data = catalog()
    out = []
    for pid in PROVIDERS:
        for mid, m in ((data.get(pid) or {}).get("models") or {}).items():
            mod = m.get("modalities") or {}
            if "image" not in (mod.get("input") or []):
                continue
            c = m.get("cost") or {}
            i, o = float(c.get("input") or 0), float(c.get("output") or 0)
            out.append({"provider": pid, "model": mid, "in": i, "out": o,
                        "free": i == 0 and o == 0, "name": m.get("name", mid)})
    return out


def page_cost(in_price: float, out_price: float) -> float:
    """单页描述成本（美元）。"""
    return (in_price * PAGE_IN_TOK + out_price * PAGE_OUT_TOK) / 1e6


def estimate(pages: int) -> dict:
    """三策略成本估算（100 页口径展示用）。"""
    vis = vision_models()
    free = [v for v in vis if v["free"]]
    pro = [v for v in vis if not v["free"]]
    def _cost(v):
        return page_cost(v["in"], v["out"]) * pages if v else None
    return {"local": 0.0, "cloud_free_model": free[0]["model"] if free else None,
            "cloud_free_per_n": _cost(free[0] if free else None),
            "cloud_pro_model": pro[0]["model"] if pro else None,
            "cloud_pro_per_n": _cost(pro[0] if pro else None),
            "note": "本地 AWQ 离线 ¥0；云描述按 models.dev 价格"}
