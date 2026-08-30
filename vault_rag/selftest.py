# -*- coding: utf-8 -*-
"""selftest.py — 系统自检：沿 MCP 同一条代码链路逐项体检。

检查项 = 用户在控制台能遇到的每个故障点：
  数据库配对 / vault 可达 / include.txt / 检索向量链（HTTP 端点、内置
  llama.cpp）/ 生成供应商（配置合法性）/ MCP 模块同步（同包同链路导入）。
"""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


def run_selftest() -> dict:
    checks: list[dict] = []
    t0 = time.time()

    def add(name: str, ok: bool, detail: str):
        checks.append({"name": name, "ok": ok, "detail": detail})

    # 1. 数据库
    try:
        from vault_rag.config import DB_PATH
        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=5)
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vectors = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        con.close()
        ok = chunks == vectors and notes > 0
        add("向量库一致性", ok, f"{notes} 篇 / {chunks} 块 / {vectors} 向量"
            + ("" if ok else " · 文本与向量不一致!"))
    except Exception as e:
        add("向量库一致性", False, f"{type(e).__name__}: {e}")

    # 2. vault 与 include.txt
    try:
        from vault_rag import scope
        from vault_rag.config import VAULT
        files = scope.collect_files()
        add("Vault 范围", len(files) > 0,
            f"{len(files)} 篇在范围内 · vault: {VAULT}")
    except Exception as e:
        add("Vault 范围", False, f"{type(e).__name__}: {e}")

    # 3. 检索向量链
    try:
        from vault_rag import search
        alive = search.embed_endpoint_alive(force=True)
        if alive:
            add("检索向量 · HTTP 端点", True, str(search.EMBED_HTTP_URL))
        else:
            from vault_rag import embed_providers as ep
            la = ep.llama_available()
            if la["ready"]:
                add("检索向量 · HTTP 端点", False,
                    f"端点离线；内置 llama.cpp 可接管: {la['gguf']}")
            else:
                add("检索向量", False, "HTTP 端点离线且内置 llama.cpp 未就绪 → 关键词模式")
    except Exception as e:
        add("检索向量", False, f"{type(e).__name__}: {e}")

    # 3b. 内置 llama.cpp 细项
    try:
        from vault_rag import embed_providers as ep
        la = ep.llama_available()
        add("内置 llama.cpp", la["ready"],
            f"服务端: {Path(la['exe']).name if la['exe'] else '未找到'} · "
            f"模型: {la['gguf'] or '未下载'}")
    except Exception as e:
        add("内置 llama.cpp", False, f"{type(e).__name__}: {e}")

    # 4. 生成供应商
    try:
        from vault_rag import webui_lib
        prof = webui_lib.active_provider()
        add("生成供应商", webui_lib.chat_ready(),
            f"{prof['name']} · {prof['model']}"
            + ("" if webui_lib.chat_ready() else " · 缺 key"))
    except Exception as e:
        add("生成供应商", False, f"{type(e).__name__}: {e}")

    # 5. MCP 同步（同包同链路：MCP 的检索/配置与本控制台共用同一模块）
    try:
        from vault_rag import rag_mcp
        add("MCP 同步", True,
            "vault_rag.rag_mcp 导入正常，与控制台共用 search/配置链路")
    except Exception as e:
        add("MCP 同步", False, f"{type(e).__name__}: {e}")

    # 6. 数据目录可写
    try:
        from vault_rag.config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        probe = DATA_DIR / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        add("数据目录可写", True, str(DATA_DIR))
    except Exception as e:
        add("数据目录可写", False, f"{type(e).__name__}: {e}")

    return {"ok": all(c["ok"] for c in checks),
            "elapsed_ms": int((time.time() - t0) * 1000),
            "checks": checks}
