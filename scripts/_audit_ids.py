# -*- coding: utf-8 -*-
"""审计:app.js 引用的所有 $("id") / getElementById vs index.html 实际定义。"""
from pathlib import Path
import re

js = Path("webui_assets/app.js").read_text(encoding="utf-8")
html = Path("webui_assets/index.html").read_text(encoding="utf-8")

used = set(re.findall(r'\$\("([^"]+)"\)', js)) | set(re.findall(r'getElementById\("([^"]+)"\)', js))
defined = set(re.findall(r'id="([^"]+)"', html))

missing = sorted(used - defined)
print("JS 引用但 HTML 缺失的 id:", missing or "无 ✓")
