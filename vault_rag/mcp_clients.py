# -*- coding: utf-8 -*-
"""mcp_clients.py — 把 vault-rag MCP 一键写入各家客户端配置。

支持格式：
    claude    JSON（mcpServers 合并）      Claude Code / 桌面版 / OpenClaw / Pi / DeepSeek Harness
    opencode  JSON（mcp 合并）             OpenCode
    codex     TOML（[mcp_servers.x] 追加） Codex

设计：写前自动备份（.bak）；幂等（重复注册为更新）。
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SERVER_ENTRY = {"command": sys.executable,
                "args": [str(REPO / "rag_mcp_server.py")]}

CLIENTS = [
    {"id": "claude-code", "name": "Claude Code", "fmt": "claude",
     "paths": [Path.home() / ".claude.json"]},
    {"id": "claude-desktop", "name": "Claude 桌面版", "fmt": "claude",
     "paths": [Path(os.environ.get("APPDATA", str(Path.home() / "AppData/Roaming")))
               / "Claude" / "claude_desktop_config.json",
               Path.home() / ".claude" / "claude_desktop_config.json"]},
    {"id": "codex", "name": "Codex", "fmt": "codex",
     "paths": [Path.home() / ".codex" / "config.toml"]},
    {"id": "opencode", "name": "OpenCode", "fmt": "opencode",
     "paths": [Path.home() / ".config" / "opencode" / "opencode.json",
               Path.home() / ".opencode" / "opencode.json"]},
    {"id": "openclaw", "name": "OpenClaw", "fmt": "claude",
     "paths": [Path.home() / ".openclaw" / "config.json",
               Path.home() / ".config" / "openclaw" / "config.json"]},
    {"id": "pi", "name": "Pi", "fmt": "claude",
     "paths": [Path.home() / ".pi" / "config.json",
               Path.home() / ".config" / "pi" / "config.json"]},
    {"id": "deepseek-harness", "name": "DeepSeek Harness 插件端", "fmt": "claude",
     "paths": [Path.home() / ".deepseek" / "harness" / "mcp.json",
               Path.home() / ".config" / "deepseek-harness" / "mcp.json"]},
]


def _config_path(c: dict) -> Path | None:
    return next((p for p in c["paths"] if p.exists()), None)


def detect(c: dict) -> dict:
    found = _config_path(c)
    registered = False
    if found:
        try:
            text = found.read_text(encoding="utf-8")
            if c["fmt"] in ("claude", "opencode"):
                data = json.loads(text)
                section = data.get("mcpServers") or data.get("mcp") or {}
                registered = "vault-rag" in section
            elif c["fmt"] == "codex":
                registered = "[mcp_servers.vault-rag]" in text
        except Exception:
            registered = False
    return {"id": c["id"], "name": c["name"], "fmt": c["fmt"],
            "config_path": str(found) if found else str(c["paths"][0]),
            "config_found": found is not None, "registered": registered}


def register(c: dict, entry: dict | None = None) -> dict:
    """写入 vault-rag MCP 条目。返回 {registered, config_path}。"""
    entry = entry or SERVER_ENTRY
    found = _config_path(c)
    if not found:
        found = c["paths"][0]
        found.parent.mkdir(parents=True, exist_ok=True)
        if c["fmt"] in ("claude", "opencode"):
            found.write_text("{}", encoding="utf-8")
        # codex TOML 允许空文件起步
    backup = found.with_suffix(found.suffix + ".bak")
    if found.exists():
        backup.write_text(found.read_text(encoding="utf-8"), encoding="utf-8")

    if c["fmt"] in ("claude", "opencode"):
        data = {}
        if found.exists() and found.stat().st_size:
            try:
                data = json.loads(found.read_text(encoding="utf-8"))
            except Exception:
                raise ValueError(f"配置文件不是合法 JSON: {found}")
        key = "mcpServers" if c["fmt"] == "claude" else "mcp"
        section = data.get(key) or {}
        if not isinstance(section, dict):
            raise ValueError(f"{found} 的 {key} 段不是对象")
        section["vault-rag"] = entry
        data[key] = section
        found.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                         encoding="utf-8")
    elif c["fmt"] == "codex":
        text = found.read_text(encoding="utf-8") if found.exists() else ""
        if "[mcp_servers.vault-rag]" not in text:
            block = ('\n[mcp_servers.vault-rag]\n'
                     f'command = "{entry["command"].replace(chr(92), "/")}"\n'
                     f'args = ["{str(entry["args"][0]).replace(chr(92), "/")}"]\n')
            found.parent.mkdir(parents=True, exist_ok=True)
            with open(found, "a", encoding="utf-8") as f:
                f.write(block)
    return {"registered": True, "config_path": str(found)}


def snippet(c: dict) -> str:
    """配置片段（无法自动写入的客户端用复制兜底）。"""
    e = SERVER_ENTRY
    cmd = str(e["command"]).replace("\\", "/")
    arg = str(e["args"][0]).replace("\\", "/")
    if c["fmt"] == "codex":
        return (f'[mcp_servers.vault-rag]\ncommand = "{cmd}"\n'
                f'args = ["{arg}"]')
    key = "mcpServers" if c["fmt"] == "claude" else "mcp"
    return (f'{{\n  "{key}": {{\n    "vault-rag": {{\n'
            f'      "command": "{cmd}",\n      "args": ["{arg}"]\n    }}\n  }}\n}}')
