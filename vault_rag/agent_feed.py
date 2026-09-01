# -*- coding: utf-8 -*-
"""agent_feed.py — 代理活动记忆流（共享大脑的心跳）。

MCP 写入工具（write/update/delete/restore_note）经 wrap() 挂钩后，
每次代理改动 vault 都落一条 JSONL 事件；webui 读 tail() 渲染记忆流页。
数据落 data/agent_log.jsonl（gitignored）。
"""
from __future__ import annotations

import functools
import json
import time
from pathlib import Path

from vault_rag.config import DATA_DIR

AGENT_LOG = DATA_DIR / "agent_log.jsonl"


def log_event(tool: str, action: str, path: str = "",
              detail: str = "", client: str = "") -> None:
    """追加一条代理活动事件（失败绝不抛出——日志不能反噬写入）。"""
    try:
        AGENT_LOG.parent.mkdir(parents=True, exist_ok=True)
        evt = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "tool": tool,
               "action": action, "path": path,
               "detail": (detail or "")[:200], "client": client or "agent"}
        with open(AGENT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except OSError:
        pass


def wrap(fn):
    """包装 MCP 写入工具：成功后记一条活动事件。签名经 functools.wraps 保留。"""
    action = {"write_note": "写入", "update_note": "修改",
              "delete_note": "删除", "restore_note": "恢复"}.get(
                  getattr(fn, "__name__", ""), "操作")

    @functools.wraps(fn)
    def _wrapped(*args, **kwargs):
        result = fn(*args, **kwargs)
        try:
            path = kwargs.get("path") or kwargs.get("rel_path") or (
                args[0] if args else "")
            log_event(fn.__name__, action, str(path)[:160])
        except Exception:
            pass
        return result

    return _wrapped


def tail(limit: int = 50) -> list[dict]:
    """读最近 limit 条事件（新在前）。"""
    try:
        lines = AGENT_LOG.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in reversed(lines):
        if len(out) >= max(1, limit):
            break
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
