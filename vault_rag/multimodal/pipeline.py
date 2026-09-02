# -*- coding: utf-8 -*-
"""pipeline.py — 多模态一键处理编排：三策略路由 + 进度 + 检索入口。

策略（2026-09-01 用户访谈定稿）：
  budget      省钱：纯本地——页图 AWQ 嵌入 + 文字层，零 API，离线可用
  balanced    平衡：每页云端描述（默认 Agnes 视觉免费）+ 文字层，无复盘
  performance 高性能：云端描述 + 文字层 + 页间关联复盘（LLM 综合摘要）

模型/供应商价格来自 models.dev（cc-switch 同源）；本地 AWQ-4bit 已在
models/Qwen3-VL-Embedding-2B-AWQ-4bit（2026-08-28 三轮实测图像侧修复）。
"""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from vault_rag.config import BASE_DIR
from vault_rag.multimodal import office, store

VL_MODEL_DIR = BASE_DIR / "models" / "Qwen3-VL-Embedding-2B-AWQ-4bit"
STRATEGIES = ("budget", "balanced", "performance")

state: dict = {"running": False, "file": "", "page": 0, "total": 0,
               "done": 0, "ok": None, "log": "", "finished": 0.0}
_lock = threading.Lock()

_emb = None                 # 本地 VL embedder 单例（懒加载，进程内复用）


def current_strategy() -> str:
    from vault_rag import webui_lib as lib
    return (lib.load_local_settings().get("mm_strategy")
            or "balanced")


def set_strategy(s: str) -> None:
    if s not in STRATEGIES:
        raise ValueError(f"未知策略: {s}")
    from vault_rag import webui_lib as lib
    lib.save_local_settings({"mm_strategy": s})


def _local_embedder():
    """懒加载本地 AWQ embedder（首次 ~30-60s，之后进程内复用）。"""
    global _emb
    if _emb is None:
        if not VL_MODEL_DIR.exists():
            raise FileNotFoundError(f"本地视觉模型缺失: {VL_MODEL_DIR}")
        import numpy as np
        import torch
        torch.set_num_threads(int(__import__("os").environ.get("RAG_TORCH_THREADS", "10")))
        from vault_rag.multimodal.vl_embedder import Qwen3VLEmbedder
        _emb = Qwen3VLEmbedder(model_name_or_path=str(VL_MODEL_DIR),
                               torch_dtype=torch.float16)
    return _emb


def embed_image(img_path: str):
    import numpy as np
    v = _local_embedder().process([{"image": img_path}]).float().cpu().numpy().reshape(-1)
    return v / max(float(np.linalg.norm(v)), 1e-9)


def embed_text(text: str):
    import numpy as np
    v = _local_embedder().process([{"text": text[:512]}]).float().cpu().numpy().reshape(-1)
    return v / max(float(np.linalg.norm(v)), 1e-9)


CAPTION_PROMPT = ("用中文描述这一页文档/幻灯片的内容，供检索使用：要点列表、"
                  "图表类型与结论、关键数字。150 字以内，只输出描述本身。")


def _caption_page(img_path: str | None, text: str) -> str:
    """云端描述：agnes-2.5-flash 免费。图与文字层一起给，描述更准。"""
    from vault_rag import webui_lib as lib
    content_text = f"页面文字：\n{text[:600]}" if text else ""
    if img_path:
        raw = Path(img_path).read_bytes()
        prompt = (CAPTION_PROMPT + ("\n" + content_text if content_text else ""))
        return lib.vision_chat(prompt, raw).strip()
    if content_text:                      # 纯文字页：走普通对话即可
        return lib.chat_once([{"role": "user",
                               "content": f"用中文概括以下页面要点，100字内：\n{text[:1500]}"}],
                             temperature=0.2).strip()
    return ""


def _review(pages_text: list[str], src: str) -> str:
    """高性能档复盘：把全部页描述交给 LLM 综合关联，产出全文脉络摘要。"""
    from vault_rag import webui_lib as lib
    joined = "\n".join(f"[{i + 1}] {t[:200]}" for i, t in enumerate(pages_text) if t)
    out = lib.chat_once([{"role": "user", "content":
                          f"以下是《{Path(src).name}》逐页要点。请输出整体脉络综述："
                          f"主题、各部分关联、3-5 条核心结论。300字内。\n{joined}"}],
                        temperature=0.2)
    return (out or "").strip()


def ingest_file(path: str, strategy: str | None = None,
                progress: bool = True) -> dict:
    """一键处理：拆页 → 按策略产块 → 入库。已处理且未变更则秒回。"""
    srcp = Path(path).resolve()
    src = str(srcp)
    strategy = strategy or current_strategy()
    st = srcp.stat().st_mtime
    if store.source_current(src, st):
        return {"ok": True, "skipped": "已索引且未变更", "src": src}
    kind = Path(src).suffix.lower().lstrip(".")
    pages = office.split_any(src)
    if progress:
        state.update(running=True, file=src, page=0, total=len(pages),
                     done=0, ok=None, log="", finished=0.0)
    try:
        store.delete_source(src)
        captions: list[str] = []
        for p in pages:
            if p.text.strip():
                store.add_chunk(src, p.page, "text", p.text)
            if strategy == "budget":
                if p.img_path:
                    store.add_chunk(src, p.page, "image-page", p.text[:200],
                                    vec=embed_image(p.img_path),
                                    model="Qwen3-VL-Embedding-2B-AWQ-4bit")
            else:                              # balanced / performance
                cap = ""
                try:
                    cap = _caption_page(p.img_path, p.text)
                except Exception as e:         # 描述失败不吞页：留痕继续
                    cap = ""
                    if progress:
                        state["log"] = (state["log"] + f"\np{p.page}: {e}").strip()[-500:]
                if cap:
                    captions.append(cap)
                    store.add_chunk(src, p.page, "caption", cap)
            if progress:
                state["done"] = p.page
        if strategy == "performance" and len(captions) >= 2:
            summary = _review(captions, src)
            if summary:
                store.add_chunk(src, 0, "summary", summary)
        store.register_source(src, kind, len(pages), strategy)
        if progress:
            state.update(running=False, ok=True, finished=time.time())
        return {"ok": True, "src": src, "pages": len(pages), "strategy": strategy}
    except Exception as e:
        if progress:
            state.update(running=False, ok=False,
                         log=f"{type(e).__name__}: {e}\n"
                             f"{traceback.format_exc()[-300:]}",
                         finished=time.time())
        store.register_source(src, kind, len(pages), strategy, status=f"error: {e}")
        return {"ok": False, "error": f"{type(e).__name__}: {e}", "src": src}


def ingest_async(path: str, strategy: str | None = None) -> None:
    """后台线程执行（端点立刻返回，进度走 /api/mm/status）。"""
    def _run():
        with _lock:
            try:
                ingest_file(path, strategy)
            except Exception:
                state.update(running=False, ok=False,
                             log=f"{type(e).__name__}: {e}")
    threading.Thread(target=_run, daemon=True,
                     name="mm-ingest").start()


def search(query_text: str, top_k: int = 5, with_vec: bool | None = None) -> list[dict]:
    """多模态检索入口：FTS(描述/文字层/复盘) + 可选向量（本地模型已载或强制）。"""
    qv = None
    if with_vec is None:
        with_vec = _emb is not None or store.stats()["vectors"] > 0
    if with_vec and store.stats()["vectors"] > 0:
        try:
            qv = embed_text(query_text)
        except Exception:
            qv = None
    return store.search(query_vec=qv, query_text=query_text, top_k=top_k)


# ---------------- 识图校准（一次性评估三路线，动态决策依据） ----------------

_CASES = [  # (绘图函数, 正确查询关键词, 评测关键词列表)
    ("red_rect", "一张纯红色的方块图", "红"),
    ("blue_circle", "一个蓝色的圆形", "蓝"),
    ("green_tri", "一个绿色的三角形", "绿"),
    ("yellow_star", "一颗黄色的星形", "黄"),
]


def _case_image(kind: str) -> str:
    from PIL import Image, ImageDraw
    d = DATA_DIR_CALIB
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"case-{kind}.png"
    if p.exists():
        return str(p)
    im = Image.new("RGB", (256, 256), "white")
    dr = ImageDraw.Draw(im)
    if kind == "red_rect":
        dr.rectangle([48, 48, 208, 208], fill="#dd2222")
    elif kind == "blue_circle":
        dr.ellipse([48, 48, 208, 208], fill="#2255dd")
    elif kind == "green_tri":
        dr.polygon([(128, 40), (228, 216), (28, 216)], fill="#22aa44")
    elif kind == "yellow_star":
        import math
        pts = [(128 + 90 * math.cos(-math.pi / 2 + i * 4 * math.pi / 5),
                128 + 90 * math.sin(-math.pi / 2 + i * 4 * math.pi / 5))
               for i in range(5)]
        dr.polygon(pts, fill="#eedd22")
    im.save(p)
    return str(p)


DATA_DIR_CALIB = BASE_DIR / "data" / "_calib"


def calibrate() -> dict:
    """合成图 4 案例：本地=向量判别方向；云端=描述含关键词。结果存 local_settings。"""
    local_ok = local_n = cloud_ok = cloud_n = 0
    details = []
    for kind, _q, keyword in _CASES:
        img = _case_image(kind)
        # 本地：正确查询 vs 反义查询的余弦差
        try:
            v = embed_image(img)
            import numpy as np
            s_good = float(embed_text(f"一张{keyword[0]}色的图形") @ v)
            s_bad = float(embed_text("一张完全空白纯白的图片") @ v)
            ok = s_good > s_bad
            local_n += 1
            local_ok += ok
            details.append(f"本地[{kind}] {s_good:+.3f} vs {s_bad:+.3f} {'✓' if ok else '✗'}")
        except Exception as e:
            details.append(f"本地[{kind}] 失败: {e}")
        # 云端：描述含关键词
        try:
            cap = _caption_page(img, "")
            ok = keyword[0] in cap
            cloud_n += 1
            cloud_ok += ok
            details.append(f"云端[{kind}] {cap[:40]} {'✓' if ok else '✗'}")
        except Exception as e:
            details.append(f"云端[{kind}] 失败: {e}")
    res = {
        "local": {"pass": local_ok, "n": local_n},
        "cloud": {"pass": cloud_ok, "n": cloud_n},
        "details": details, "time": time.strftime("%Y-%m-%d %H:%M"),
    }
    from vault_rag import webui_lib as lib
    lib.save_local_settings({"mm_calib": res})
    return res
