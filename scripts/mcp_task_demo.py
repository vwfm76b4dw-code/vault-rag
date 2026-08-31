# -*- coding: utf-8 -*-
"""mcp_task_demo.py — 真实任务端到端：MCP 检索 → 上下文组装 → 云端生成 → 引用验收。

模拟 Claude Code 的实际工作流：
    1. 通过 MCP 协议调 semantic_search 拿知识库片段
    2. 组装上下文（与控制台同一 build_messages）
    3. 交给生成供应商出回答
    4. 校验回答中的 [n] 引用与来源对应
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from mcp_smoke import McpClient, SERVERS          # noqa: E402
from vault_rag import webui_lib as lib            # noqa: E402

QUERY = sys.argv[1] if len(sys.argv) > 1 else "agent 怎么防遗忘"


def mcp_semantic_search(query: str, top_k: int = 4) -> list[dict]:
    """经 MCP 协议调 vault_rag.rag_mcp 的 semantic_search。"""
    cfg = SERVERS["rag"]
    cli = McpClient(cfg["cmd"], cfg["cwd"])
    try:
        cli.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "task", "version": "1.0"}}})
        cli.wait_resp(1, 60)
        cli.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        cli.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "semantic_search",
                             "arguments": {"query": query, "top_k": top_k}}})
        resp = cli.wait_resp(3, 180)
        content = resp.get("result", {}).get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        return json.loads(text)["results"]
    finally:
        cli.close()


def main() -> int:
    print(f"真实任务：{QUERY}\n")
    print("── 步骤 1：MCP 协议检索（vault_rag.rag_mcp）────────")
    results = mcp_semantic_search(QUERY, top_k=4)
    for i, r in enumerate(results, 1):
        print(f"  [{i}] {r['score']:.3f} {r['path']}")

    chunks = [{"rel_path": r["path"], "section": "", "text": r["snippet"],
               "superseded": False} for i, r in enumerate(results, 1)]
    messages = lib.build_messages(QUERY, chunks)

    print("── 步骤 2：云端生成（当前生效供应商）────────")
    prof = lib.active_provider()
    print(f"  供应商: {prof['name']} · {prof['model']}")
    answer = lib.chat_once(messages)

    print("── 步骤 3：引用验收 ────────")
    import re
    cites = sorted(set(re.findall(r"\[(\d)\]", answer)))
    valid = all(1 <= int(c) <= len(results) for c in cites)
    print(f"  回答 {len(answer)} 字 · 引用编号 {cites} · "
          f"{'✓ 全部有效' if valid and cites else '⚠ 无引用或越界'}")

    print("\n════ 最终回答 ════")
    print(answer[:800])
    return 0 if cites and valid else 1


if __name__ == "__main__":
    sys.exit(main())
