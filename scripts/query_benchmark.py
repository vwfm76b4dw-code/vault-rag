# -*- coding: utf-8 -*-
"""query_benchmark.py — 真实项目查询准确性基准（经 MCP 协议实测）。

每条查询带 ground truth（已知目标文档片段），统计 hit@3 / hit@8 / MRR。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from mcp_smoke import McpClient, SERVERS  # noqa: E402

# (查询, 期望路径包含片段, 说明)
CASES = [
    ("agent 怎么防遗忘", "AI-Agent-记忆与知识管理深度研究", "记忆机制研究笔记"),
    ("Mem0 持久记忆框架", "Mem-2026-08-05", "Mem0 研究笔记"),
    ("OpenSPH 科学计算框架", "OpenSPH-2026-08-08", "GitHub 热门研究"),
    ("C2PA 内容凭证规范", "C2PA-Specification-2026-08", "合成媒体验证研究"),
    ("claude-obsidian 项目研究", "claude-obsidian项目研究-2026-08-11", "项目研究笔记"),
    ("Cadnano DNA 折纸设计", "Cadnano2.5-DNA折纸设计", "纳米技术研究"),
    ("StellarSolver 天文求解器", "23-StellarSolver-2026-08-08", "GitHub 热门研究"),
    ("HNSWLIB 轻量向量索引库", "HNSWLIB-轻量HNSW索引库", "向量库竞品研究"),
    ("冒泡排序 cpp", "冒泡排序.cpp", "用户上传的代码文件"),
    ("vault-rag 全链条生态组成", "vault-rag全链条生态", "本系统持久记忆"),
]


def mcp_search(query: str, top_k: int = 8) -> list[dict]:
    cfg = SERVERS["rag"]
    cli = McpClient(cfg["cmd"], cfg["cwd"])
    try:
        cli.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                             "clientInfo": {"name": "bench", "version": "1.0"}}})
        cli.wait_resp(1, 120)
        cli.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        cli.send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                  "params": {"name": "semantic_search",
                             "arguments": {"query": query, "top_k": top_k}}})
        resp = cli.wait_resp(3, cfg["timeout"])
        content = resp.get("result", {}).get("content", [])
        text = "".join(c.get("text", "") for c in content if c.get("type") == "text")
        return json.loads(text)["results"]
    finally:
        cli.close()


def main() -> int:
    print("真实项目查询准确性基准(经 MCP 协议)\n" + "=" * 52)
    hits3 = hits8 = 0
    mrr_sum = 0.0
    rows = []
    for q, expect, note in CASES:
        try:
            results = mcp_search(q, top_k=8)
        except Exception as e:
            rows.append((q, expect, note, -1, f"异常 {e}"))
            hits8 = hits8
            continue
        rank = next((i for i, r in enumerate(results, 1)
                     if expect in r.get("path", "")), -1)
        hit3 = 1 if 1 <= rank <= 3 else 0
        hit8 = 1 if rank > 0 else 0
        mrr_sum += (1.0 / rank) if rank > 0 else 0.0
        hits3 += hit3
        hits8 += hit8
        mark = "✓" if rank == 1 else ("△" if rank > 0 else "✗")
        rows.append((q, expect, note, rank, mark))
        print(f"  {mark} rank={rank if rank > 0 else '-':>2}  {q}  →  {expect[:44]}")
    n = len(CASES)
    mrr = mrr_sum / n
    print("=" * 52)
    print(f"hit@3: {hits3}/{n} ({hits3 / n * 100:.0f}%)   "
          f"hit@8: {hits8}/{n} ({hits8 / n * 100:.0f}%)   MRR: {mrr:.2f}")

    report = {"time": time.strftime("%Y-%m-%d %H:%M"), "cases": n,
              "hit3": hits3, "hit8": hits8, "mrr": round(mrr, 3),
              "rows": [{"query": q, "expect": e, "note": note,
                        "rank": rank, "mark": mark}
                       for q, e, note, rank, mark in rows]}
    out = REPO / "data" / "query_benchmark_last.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"明细已存 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
