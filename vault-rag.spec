# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 产物 dist/vault-rag/（onedir，含 vault-rag.exe）

构建：python -m PyInstaller vault-rag.spec --noconfirm
要点：
- onedir 而非 onefile：torch 全量打单文件会每次启动解压数 GB
- transformers 的 AutoModel/AutoTokenizer 按需动态 import 模型子模块，
  静态分析看不到，必须显式 hiddenimports（否则打包后加载模型报 ModuleNotFoundError）
- console=False：无黑框；日志由 webui.main() 落到 data/webui.log
"""
from PyInstaller.utils.hooks import collect_submodules

hidden = [
    # uvicorn 的平台组件全是动态选择
    "uvicorn.logging", "uvicorn.loops", "uvicorn.loops.auto",
    "uvicorn.protocols", "uvicorn.protocols.http", "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets", "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan", "uvicorn.lifespan.on",
    "anyio._backends._asyncio",
    # pywebview 的 Windows 后端为运行时按需加载
    "webview.platforms.edgechromium", "webview.platforms.winforms",
    # transformers 动态 import Qwen3 模型实现（检索模型 Qwen3-Embedding-0.6B）
    *collect_submodules("transformers.models.qwen3"),
    "transformers.models.auto.modeling_auto",
    "transformers.models.auto.tokenization_auto",
    "transformers.models.auto.configuration_auto",
]

a = Analysis(
    ["webui.py"],
    pathex=[],
    binaries=[],
    datas=[
        ("webui_assets", "webui_assets"),
        ("include.txt", "."),          # 打包态首运拷到 exe 旁
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "pandas", "tkinter", "PyQt5", "PyQt6", "PySide2", "PySide6"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="vault-rag",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                     # 不弹控制台黑框
    disable_windowed_traceback=False,
    icon="vault-rag.ico",              # 同款 LOGO 图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="vault-rag",
)
