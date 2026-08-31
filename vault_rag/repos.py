# -*- coding: utf-8 -*-
"""repos.py — 多 RAG 仓库管理：注册表 / 新建 / 切换（运行内生效+持久化）。

仓库 = 一套独立索引产物（qwen_rag.db + include.txt 模板 + gguf 共享）。
注册表存 BASE_DIR/repos.json（跨仓库元数据，不随单仓库数据走）。

切换语义：
    1. 校验目标目录（存在 qwen_rag.db，或为空目录视为新仓库）
    2. 写 data_dir.txt（重启持久）+ os.environ（子进程一致）
    3. 就地刷新已加载模块的路径属性并清缓存（控制台进程即时生效）
    注：独立 MCP 进程需重启后才跟随新仓库（文档已注明）。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from vault_rag.config import BASE_DIR, DATA_DIR


def registry_path() -> Path:
    return BASE_DIR / "repos.json"


def load_registry() -> list[dict]:
    try:
        return json.loads(registry_path().read_text(encoding="utf-8"))
    except Exception:
        return []


def save_registry(reg: list[dict]) -> None:
    registry_path().write_text(json.dumps(reg, ensure_ascii=False, indent=2),
                               encoding="utf-8")


def current_data_dir() -> str:
    from vault_rag import config
    return str(config.DATA_DIR)          # 动态：跟随运行内切换


def apply_data_dir(new_dir: str | Path) -> None:
    """运行内切换数据目录：刷新 config 与各已加载模块的路径属性。"""
    import vault_rag.config as config

    d = Path(new_dir)
    config.DATA_DIR = d
    config.DB_PATH = d / "qwen_rag.db"
    config.RELATIONS_DB = d / "relations.db"
    config.WEIGHTS_DB = d / "weights.db"
    config.LOCAL_SETTINGS_PATH = d / "_local_settings.json"

    # 已加载模块持有的旧路径属性 → 就地刷新
    try:
        from vault_rag import search
        search.DB_PATH = config.DB_PATH
        search._CACHE["stamp"] = None
    except Exception:
        pass
    try:
        from vault_rag import webui_lib
        webui_lib.DB_PATH = config.DB_PATH
    except Exception:
        pass
    try:
        from vault_rag import repo_admin
        repo_admin.DB_PATH = config.DB_PATH
    except Exception:
        pass
    try:
        from vault_rag import webui
        webui.RAG_DB = config.DB_PATH
    except Exception:
        pass


def switch_to(name: str) -> dict:
    reg = load_registry()
    entry = next((r for r in reg if r["name"] == name), None)
    if not entry:
        raise ValueError(f"注册表中无此仓库: {name}")
    d = Path(entry["data_dir"])
    if not (d / "qwen_rag.db").exists():
        raise ValueError(f"该仓库数据目录缺少 qwen_rag.db: {d}")
    # 范围声明全局共享（多仓库 = 多套索引产物，同一采集范围）
    apply_data_dir(d)
    persist_pointer(d)
    return {"name": name, "data_dir": str(d)}


def persist_pointer(data_dir: str | Path) -> None:
    """写 data_dir.txt（exe/重启后保持指向）。"""
    try:
        (BASE_DIR / "data_dir.txt").write_text(str(data_dir), encoding="utf-8")
    except OSError:
        pass


def create_repo(name: str, data_dir: str | None = None) -> dict:
    """新建仓库：建目录 + 最小 qwen_rag.db + include.txt 模板 + 注册。"""
    import sqlite3

    d = Path(data_dir) if data_dir else DATA_DIR / f"repo-{name}"
    d.mkdir(parents=True, exist_ok=True)
    db = d / "qwen_rag.db"
    if not db.exists():
        con = sqlite3.connect(db)
        con.executescript("""
            CREATE TABLE IF NOT EXISTS notes(rel_path TEXT PRIMARY KEY, mtime REAL, n_chunks INTEGER);
            CREATE TABLE IF NOT EXISTS chunks(chunk_id INTEGER PRIMARY KEY,
                rel_path TEXT NOT NULL, seq INTEGER, section TEXT, text TEXT);
            CREATE TABLE IF NOT EXISTS blob_vectors(chunk_id INTEGER PRIMARY KEY, vec BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS embed_cache(h TEXT PRIMARY KEY, vec BLOB NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
        """)
        con.commit()
        con.close()
    inc = d / "include.txt"
    if not inc.exists():
        inc.write_text("# 新仓库范围声明\n知识/\n*.md\n", encoding="utf-8")

    reg = load_registry()
    if not any(r["name"] == name for r in reg):
        reg.append({"name": name, "data_dir": str(d)})
        save_registry(reg)
    return {"name": name, "data_dir": str(d)}


def ensure_default_registered() -> None:
    """主数据目录含 qwen_rag.db 但未登记时，自动登记为「主仓库」。"""
    reg = load_registry()
    if any(r["name"] == "主仓库" for r in reg):
        return
    if (DATA_DIR / "qwen_rag.db").exists():
        reg.append({"name": "主仓库", "data_dir": str(DATA_DIR)})
        save_registry(reg)


def discover() -> list[dict]:
    """注册表 + 当前指向，供管理页展示。"""
    ensure_default_registered()
    cur = current_data_dir()
    items = []
    for r in load_registry():
        d = Path(r["data_dir"])
        db = d / "qwen_rag.db"
        stat = {"name": r["name"], "data_dir": str(d),
                "is_current": str(d) == cur,
                "ready": db.exists(),
                "size_mb": round(db.stat().st_size / 1e6, 1) if db.exists() else 0}
        if db.exists():
            try:
                import sqlite3
                con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=3)
                stat["notes"] = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
                con.close()
            except Exception:
                stat["notes"] = "?"
        items.append(stat)
    # 当前目录若不在注册表（如默认 data），补一条只读展示
    if not any(i["data_dir"] == cur for i in items):
        items.insert(0, {"name": "(当前默认)", "data_dir": cur,
                         "is_current": True, "ready": (Path(cur) / "qwen_rag.db").exists(),
                         "size_mb": 0, "notes": "?"})
    return items
