# -*- coding: utf-8 -*-
"""mcp_probe.py — 轻量 MCP 协议探测（initialize + tools/list，不调模型）。"""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time


def quick_probe(cmd: list[str], cwd: str, expect_tools: list[str],
                timeout: float = 60.0) -> dict:
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.DEVNULL, cwd=cwd,
                            text=True, encoding="utf-8", bufsize=1)
    lines: list[str] = []
    done = threading.Event()

    def reader():
        for line in proc.stdout:
            lines.append(line.strip())
        done.set()
    threading.Thread(target=reader, daemon=True).start()

    def send(o):
        proc.stdin.write(json.dumps(o, ensure_ascii=False) + "\n")
        proc.stdin.flush()

    def wait_id(msg_id, deadline):
        while time.time() < deadline and not done.is_set():
            for line in lines:
                try:
                    m = json.loads(line)
                except Exception:
                    continue
                if m.get("id") == msg_id:
                    return m
            time.sleep(0.1)
        return None

    t_end = time.time() + timeout
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
              "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                         "clientInfo": {"name": "probe", "version": "1.0"}}})
        if not wait_id(1, t_end):
            return {"ok": False, "detail": "initialize 超时"}
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = wait_id(2, t_end)
        if not resp:
            return {"ok": False, "detail": "tools/list 超时"}
        tools = [t.get("name") for t in resp.get("result", {}).get("tools", [])]
        missing = [t for t in expect_tools if t not in tools]
        return {"ok": not missing,
                "detail": f"{len(tools)} 个工具" + (f" · 缺 {missing}" if missing else ""),
                "tools": tools}
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
    finally:
        try:
            proc.kill()
        except Exception:
            pass
