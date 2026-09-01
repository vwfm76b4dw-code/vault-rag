# -*- coding: utf-8 -*-
"""inject_feed_hook.py — 给部署版 rag-obsidian server.py 挂代理活动钩子（幂等）。

写入类 MCP 工具（write/update/delete/restore_note）成功执行后记一条
JSONL 事件到 <repo>/data/agent_log.jsonl，webui 记忆流页读取渲染。
"""
from pathlib import Path

SERVER = Path.home() / ".claude" / "mcp_servers" / "rag-obsidian" / "server.py"
REPO = Path(__file__).resolve().parent.parent
MARKER = "vault-rag agent activity feed hook"
HOOK = f'''

# ---- {MARKER} (auto-injected, idempotent) ----
try:
    import sys as _sys
    _sys.path.insert(0, r"{REPO.as_posix()}")
    from vault_rag.agent_feed import wrap as _feed_wrap
    for _name, _tool in list(mcp._tool_manager._tools.items()):
        if _name in ("write_note", "update_note", "delete_note", "restore_note"):
            _fn = getattr(_tool, "fn", None)
            if _fn is not None and not getattr(_fn, "_feed_wrapped", False):
                _tool.fn = _feed_wrap(_fn)
                _fn._feed_wrapped = True
except Exception:
    pass
'''

src = SERVER.read_text(encoding="utf-8")
if MARKER in src:
    print("already injected")
else:
    SERVER.with_suffix(".py.bak_prefeed").write_text(src, encoding="utf-8")
    SERVER.write_text(src + HOOK, encoding="utf-8")
    print("injected OK ->", SERVER)
