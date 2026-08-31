# -*- coding: utf-8 -*-
"""mcp_smoke.py — MCP 协议级真实协同测试（stdio JSON-RPC 全握手）。

用法：
    python scripts/mcp_smoke.py                 # 测全部已注册服务器
    python scripts/mcp_smoke.py --only rag      # 只测 vault_rag.rag_mcp
    python scripts/mcp_smoke.py --only obsidian # 只测注入版 rag-obsidian

流程（与 Claude Code 完全一致的客户端行为）：
    initialize → notifications/initialized → tools/list → tools/call …
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PY = sys.executable

SERVERS = {
    "rag": {
        "title": "vault_rag.rag_mcp（与控制台同步）",
        "cmd": [PY, "-m", "vault_rag.rag_mcp"],
        "cwd": str(REPO),
        "expect_tools": ["semantic_search", "hybrid_search", "rag_status", "refresh_index"],
        "call": {"name": "semantic_search",
                 "arguments": {"query": "agent 怎么防遗忘", "top_k": 3}},
        "timeout": 180,
    },
    "obsidian": {
        "title": "rag-obsidian（Claude Code 注入版）",
        "cmd": [PY, str(Path.home() / ".claude/mcp_servers/rag-obsidian/server.py")],
        "cwd": str(Path.home() / ".claude/mcp_servers/rag-obsidian"),
        "expect_tools": ["semantic_search", "get_note_relations", "note_freshness"],
        "call": {"name": "semantic_search",
                 "arguments": {"query": "agent 怎么防遗忘", "top_k": 3}},
        "timeout": 180,
    },
}


class McpClient:
    """最小 MCP stdio 客户端：行协议 + 后台读线程。"""

    def __init__(self, cmd, cwd):
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
        self.proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.DEVNULL, cwd=cwd, env=env,
                                     text=True, encoding="utf-8", bufsize=1)
        self.q: queue.Queue = queue.Queue()
        self.alive = True
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line.startswith("{"):
                try:
                    self.q.put(json.loads(line))
                except Exception:
                    pass
        self.alive = False
        self.q.put(None)

    def send(self, obj):
        self.proc.stdin.write(json.dumps(obj, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

    def wait_resp(self, msg_id: int, timeout: float) -> dict:
        t0 = time.time()
        while time.time() - t0 < timeout and self.alive:
            try:
                msg = self.q.get(timeout=1)
            except queue.Empty:
                continue
            if msg is None:
                break
            if msg.get("id") == msg_id:
                return msg
        return {"error": {"message": f"超时（{timeout}s）"}}

    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()


def run_server(name: str, cfg: dict) -> tuple[bool, list[str]]:
    print(f"\n═══ {cfg['title']} ═══")
    notes: list[str] = []
    cli = McpClient(cfg["cmd"], cfg["cwd"])
    ok = True
    try:
        # 1) initialize 握手
        cli.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "mcp_smoke", "version": "1.0"}}})
        resp = cli.wait_resp(1, 60)
        result = resp.get("result", {})
        info = result.get("serverInfo", {})
        if "serverInfo" not in result:
            ok = False
            notes.append("initialize 握手失败: " + json.dumps(resp, ensure_ascii=False)[:120])
        else:
            notes.append(f"握手 ✓ server={info.get('name')} v{info.get('version')}")
        cli.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

        # 2) tools/list
        cli.send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        resp = cli.wait_resp(2, 60)
        tools = [t["name"] for t in resp.get("result", {}).get("tools", [])]
        missing = [t for t in cfg["expect_tools"] if t not in tools]
        if missing:
            ok = False
            notes.append(f"tools/list 缺少: {missing}（现有 {len(tools)} 个）")
        else:
            notes.append(f"tools/list ✓ {len(tools)} 个工具，含全部期望项")

        # 3) tools/call semantic_search（真实查询，走真实索引/降级链）
        t0 = time.time()
        cli.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": cfg["call"]["name"],
                             "arguments": cfg["call"]["arguments"]}})
        resp = cli.wait_resp(3, cfg["timeout"])
        dt = time.time() - t0
        if "error" in resp:
            ok = False
            notes.append(f"tools/call 失败: {json.dumps(resp['error'], ensure_ascii=False)[:140]}")
        else:
            content = resp.get("result", {}).get("content", [])
            text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
            if not text:
                ok = False
                notes.append(f"tools/call 空结果（{dt:.1f}s）")
            else:
                notes.append(f"tools/call ✓ {dt:.1f}s · 返回 {len(text)} 字符 · 预览: {text[:80]}")
    finally:
        cli.close()
    return ok, notes


def main() -> int:
    only = None
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1]
    targets = {k: v for k, v in SERVERS.items() if only is None or only in k}
    all_ok = True
    print("MCP ↔ Claude Code 协同测试（协议级真实握手 + 真实查询）")
    for name, cfg in targets.items():
        if name == "obsidian" and not Path(cfg["cmd"][-1]).exists():
            print(f"\n═══ {cfg['title']} ═══\n跳过：server.py 不存在")
            continue
        try:
            ok, notes = run_server(name, cfg)
            all_ok &= ok
            print("  " + "\n  ".join(notes))
            print(f"  ⇒ {'✓ 通过' if ok else '✗ 未通过'}")
        except Exception as e:
            all_ok = False
            print(f"  ✗ 异常: {type(e).__name__}: {e}")
    print("\n总结:", "✓ 全部通过" if all_ok else "✗ 存在未通过项")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
