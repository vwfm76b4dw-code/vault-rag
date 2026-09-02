# -*- coding: utf-8 -*-
"""testlib.py — 错题测试 RAG 库（独立于主库与 multimodal.db）。

用户指令：单独建一个错题测试 RAG 库，用 Qwen3-VL-Embedding-2B（FP8）索引。
内容 = vault/错题/ 的笔记（文本）+ 对应原始拍照（图像），同一 VL 向量空间。
入库走 store 的表结构，但 MM_DB 指向独立的 data/mistake_test.db。

注意（2026-08-28 研究结论）：FP8 版图像侧曾实测坍缩（图↔图 0.972 不可分），
build() 内置合成图健康检查，坍缩会写进 health 报告——用数据说话。

用法：
    python -m vault_rag.multimodal.testlib build   [模型目录]
    python -m vault_rag.multimodal.testlib query "查询词"
"""
from __future__ import annotations

import re
import sys
import time
from pathlib import Path

from vault_rag.config import BASE_DIR, DATA_DIR, VAULT

TEST_DB = DATA_DIR / "mistake_test.db"
DEFAULT_MODEL = BASE_DIR / "models" / "Qwen3-VL-Embedding-2B-FP8"
FALLBACK_MODEL = BASE_DIR / "models" / "Qwen3-VL-Embedding-2B-AWQ-4bit"
MISTAKE_DIR = VAULT / "错题"


def _find_photo(source_line: str) -> Path | None:
    """按 frontmatter source 字段找留档原图（data/uploads/**/mistake-*）。"""
    m = re.search(r"source:\s*(mistake-[0-9a-f]+-.+)", source_line or "")
    if not m:
        return None
    for p in (DATA_DIR / "uploads").rglob(m.group(1)):
        return p
    return None


def _resolve_model(arg: str | None) -> Path:
    for cand in ([Path(arg)] if arg else []) + [DEFAULT_MODEL, FALLBACK_MODEL]:
        if cand and Path(cand).exists():
            return Path(cand)
    raise FileNotFoundError("本地无 VL 模型（FP8/AWQ 均缺）")


def _load(model_dir: Path):
    import numpy as np
    import torch
    torch.set_num_threads(int(__import__("os").environ.get("RAG_TORCH_THREADS", "10")))
    from vault_rag.multimodal.vl_embedder import Qwen3VLEmbedder
    emb = Qwen3VLEmbedder(model_name_or_path=str(model_dir),
                          torch_dtype=torch.float16)

    def enc_img(p: str):
        v = emb.process([{"image": p}]).float().cpu().numpy().reshape(-1)
        return v / max(float(np.linalg.norm(v)), 1e-9)

    def enc_text(t: str):
        v = emb.process([{"text": t[:512]}]).float().cpu().numpy().reshape(-1)
        return v / max(float(np.linalg.norm(v)), 1e-9)

    return emb, enc_img, enc_text


def _health(enc_img, enc_text) -> dict:
    """合成图判别力健康检查（FP8 坍缩 historically 在此暴露）。"""
    from vault_rag.multimodal.pipeline import _CASES, _case_image
    ok, n, detail = 0, 0, []
    for kind, _q, keyword in _CASES:
        img = _case_image(kind)
        s_good = float(enc_text(f"一张{keyword[0]}色的图形") @ enc_img(img))
        s_bad = float(enc_text("一张完全空白纯白的图片") @ enc_img(img))
        ok += s_good > s_bad
        n += 1
        detail.append(f"{kind} {s_good:+.3f} vs {s_bad:+.3f} {'✓' if s_good > s_bad else '✗'}")
    # 图↔图判别（FP8 曾 0.972 坍缩）
    a = enc_img(_case_image("red_rect"))
    b = enc_img(_case_image("blue_circle"))
    return {"pass": f"{ok}/{n}", "img_img_sim": round(float(a @ b), 3), "detail": detail}


def build(model_arg: str | None = None) -> dict:
    """建库：错题笔记 + 原拍照 → VL 嵌入 → mistake_test.db。"""
    from vault_rag.multimodal import store
    store.MM_DB = TEST_DB                       # 本库独立（复用同一套表结构）
    model_dir = _resolve_model(model_arg)
    _emb, enc_img, enc_text = _load(model_dir)
    health = _health(enc_img, enc_text)

    notes = sorted(MISTAKE_DIR.glob("*.md"))
    if not notes:
        raise FileNotFoundError(f"{MISTAKE_DIR} 下没有错题笔记")
    n_img = n_note = 0
    for note in notes:
        text = note.read_text(encoding="utf-8")
        title = note.stem
        body = text.split("---", 2)[-1]
        # 原拍照 → 图像向量（text 字段放笔记标题供 FTS 命中）
        photo = _find_photo(text[:400])
        if photo:
            store.add_chunk(src=str(photo), page=1, kind="photo",
                            text=f"{title}（错题拍照）",
                            vec=enc_img(str(photo)),
                            model=model_dir.name)
            n_img += 1
        # 笔记全文 → 文本向量
        store.add_chunk(src=str(note), page=1, kind="note",
                        text=body[:2000],
                        vec=enc_text(title + " " + body[:400]),
                        model=model_dir.name)
        n_note += 1
    return {"model": model_dir.name, "notes": n_note, "photos": n_img,
            "health": health, "stats": store.stats()}


def query(q: str, top_k: int = 5, model_arg: str | None = None) -> list[dict]:
    """查询：同一 VL 模型编码问题 → 图像+笔记双路召回。"""
    from vault_rag.multimodal import store
    store.MM_DB = TEST_DB
    model_dir = _resolve_model(model_arg)
    _emb, enc_img, enc_text = _load(model_dir)
    return store.search(query_vec=enc_text(q), query_text=q, top_k=top_k)


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "build"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    if cmd == "build":
        r = build(arg)
        print(f"建库完成：模型={r['model']} 笔记={r['notes']} 拍照={r['photos']}")
        print(f"健康检查: pass={r['health']['pass']} 图↔图相似={r['health']['img_img_sim']}"
              f"（<0.85 为正常，~0.97 即坍缩）")
        for d in r["health"]["detail"]:
            print("  ", d)
        print("stats:", r["stats"])
    elif cmd == "query":
        for h in query(arg or "矩形折叠求距离", top_k=5):
            print(f"[{h['score']:.3f}] {h['kind']} {Path(h['src']).name}"
                  f" :: {h['text'][:60]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
