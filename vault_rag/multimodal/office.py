# -*- coding: utf-8 -*-
"""office.py — PDF/PPTX 按页拆解（纯逻辑，不碰网络/模型）。

PDF: pypdfium2 渲染整页 PNG + 文字层提取；无文字层（扫描版）标记 scan=True。
PPTX: zipfile+XML 零依赖，每页 = 幻灯片文本 + 内嵌图片归属。
产物统一为 Page(img_path, text, page, scan) 列表，交给 pipeline 路由。
"""
from __future__ import annotations

import os
import re
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

PDF_SCALE = 150 / 72          # 渲染 DPI


@dataclass
class Page:
    img_path: str | None      # 页面图（PDF 渲染图 / PPTX 内嵌首图）
    text: str                 # 该页文字（PPTX 为全部文本框拼接）
    page: int                 # 1-based
    scan: bool = False        # 无文字层（扫描版）


def _img_dir(src: Path) -> Path:
    d = src.parent / (src.stem + "_pages")
    d.mkdir(parents=True, exist_ok=True)
    return d


def split_pdf(src: str | Path, out_dir: Path | None = None) -> list[Page]:
    """PDF → 每页(渲染PNG + 文字)。扫描版页 scan=True、无渲染也回退整页图。"""
    import pypdfium2 as pdfium
    src = Path(src)
    out = out_dir or _img_dir(src)
    out.mkdir(parents=True, exist_ok=True)
    pdf = pdfium.PdfDocument(str(src))
    pages: list[Page] = []
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            tp = page.get_textpage()
            text = (tp.get_text_bounded() or "").strip()
            bmp = page.render(scale=PDF_SCALE)
            img = bmp.to_pil()
            img_path = out / f"{src.stem}-p{i + 1}.png"
            img.save(img_path)
            pages.append(Page(str(img_path), text, i + 1, scan=len(text) < 8))
    finally:
        pdf.close()
    return pages


_NS = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}


def split_pptx(src: str | Path, out_dir: Path | None = None) -> list[Page]:
    """PPTX → 每页(文本框拼接 + 内嵌图片抽出落盘)。"""
    src = Path(src)
    out = out_dir or _img_dir(src)
    out.mkdir(parents=True, exist_ok=True)
    pages: list[Page] = []
    with zipfile.ZipFile(src) as z:
        slide_names = sorted(
            (n for n in z.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)", n).group(1)))
        media = {os.path.basename(n): n for n in z.namelist()
                 if n.startswith("ppt/media/")}
        for idx, sn in enumerate(slide_names, 1):
            root = ET.fromstring(z.read(sn))
            texts = [t.text for t in root.iter(f"{{{ _NS['a'] }}}t")
                     if t.text and t.text.strip()]
            text = "\n".join(texts).strip()
            img_path = None
            for blip in root.iter(f"{{{ _NS['a'] }}}blip"):
                rid = blip.get(f"{{{ 'http://schemas.openxmlformats.org/officeDocument/2006/relationships' }}}embed")
                if not rid:
                    continue
                rels = f"ppt/slides/_rels/{Path(sn).name}.rels"
                if rels in z.namelist():
                    rroot = ET.fromstring(z.read(rels))
                    for rel in rroot:
                        if rel.get("Id") == rid:
                            tgt = rel.get("Target", "").replace("../", "ppt/")
                            base = os.path.basename(tgt)
                            if base in media:
                                raw = z.read(media[base])
                                ip = out / f"{src.stem}-s{idx}-{base}"
                                ip.write_bytes(raw)
                                try:
                                    Image.open(ip).verify()
                                    img_path = str(ip)
                                except Exception:
                                    ip.unlink(missing_ok=True)
                    if img_path:
                        break
            pages.append(Page(img_path, text, idx, scan=len(text) < 8))
    return pages


def split_any(src: str | Path, out_dir: Path | None = None) -> list[Page]:
    ext = Path(src).suffix.lower()
    if ext == ".pdf":
        return split_pdf(src, out_dir)
    if ext == ".pptx":
        return split_pptx(src, out_dir)
    raise ValueError(f"不支持的格式: {ext}（当前支持 pdf/pptx）")
