# -*- coding: utf-8 -*-
"""验收总测脚本：此前访谈目标 + 指定笔记直查。跑完打印打分卡。"""
import io
import json
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

import requests

BASE = "http://127.0.0.1:8899"
card = []          # (模块, 项目, 结果✓/✗, 说明)


def add(mod, item, ok, note=""):
    card.append((mod, item, "✓" if ok else "✗", note))
    print(f"  {'✓' if ok else '✗'} {item}  {note}")


# ============ A. 指定笔记直查 · 主库（vault 3000+ 篇 + 上传文件） ============
print("═ A. 指定笔记直查 · 主库 ═")
MAIN_CASES = [
    ("冒泡排序.cpp", "冒泡排序.cpp"),                     # 上传的代码文件
    ("HNSWLIB 轻量HNSW索引库", "HNSWLIB-轻量HNSW索引库"),  # vault 研究笔记
    ("vault-rag 全链条生态组成", "vault-rag全链条生态"),     # 记忆目录
    ("AI Agent 记忆与知识管理研究", "AI-Agent-记忆与知识管理"),
    ("Claude Obsidian 项目研究", "claude-obsidian项目研究"),
]
a_ok = 0
for q, expect in MAIN_CASES:
    r = requests.post(f"{BASE}/api/search", json={"q": q, "k": 3}, timeout=60).json()
    top = r["results"][0]["rel_path"] if r.get("results") else ""
    ok = expect in top
    a_ok += ok
    add("A 主库直查", f"『{q[:18]}』", ok, f"top1={top[:48]}")
print(f"  → 主库直查 {a_ok}/{len(MAIN_CASES)}\n")

# ============ B. 指定笔记直查 · 错题测试库（VL FP8 视觉库） ============
print("═ B. 指定笔记直查 · 错题测试库 ═")
from vault_rag.multimodal import testlib
MM_CASES = [
    ("矩形的性质 折叠 30度", "矩形的性质"),
    ("三角形中位线定理 全等", "三角形中位线定理"),
    ("图形平移 对应点连线相等", "图形平移的性质"),
    ("梯形中位线 勾股定理", "梯形中位线性质"),
]
b_ok = 0
for q, expect in MM_CASES:
    hits = testlib.query(q, top_k=3)
    top = hits[0]["src"].split("\\")[-1] if hits else ""
    ok = expect in top
    b_ok += ok
    add("B 错题库直查", f"『{q[:18]}』", ok, f"top1={top[:44]}")
print(f"  → 错题库直查 {b_ok}/{len(MM_CASES)}\n")

# ============ C. 记忆心跳真 E2E：MCP write_note → feed → 头条 ============
print("═ C. 记忆心跳（代理写入→记忆流→头条） ═")
sys.path.insert(0, str(REPO / "scripts"))
from mcp_smoke import McpClient, SERVERS
cfg = SERVERS["obsidian"]
cli = McpClient(cfg["cmd"], cfg["cwd"])
cli.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "acceptance", "version": "1.0"}}})
cli.wait_resp(1, 60)
cli.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
cli.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
    "name": "write_note",
    "arguments": {"path": "记忆/vault-rag验收冒烟.md", "title": "验收冒烟",
                  "content": "本条由验收脚本经真实 MCP write_note 写入，用于验证记忆心跳链路。",
                  "tags": "测试"}}})
resp = cli.wait_resp(2, 60)
content = "".join(c.get("text", "") for c in resp.get("result", {}).get("content", []))
c1 = '"success": true' in content or '"success":true' in content
add("C 记忆心跳", "MCP write_note 写入", c1, content[:60])

time.sleep(1)
log = (REPO / "data" / "agent_log.jsonl")
c2 = log.exists() and "vault-rag验收冒烟" in log.read_text(encoding="utf-8")
add("C 记忆心跳", "agent_log.jsonl 事件落盘", c2)

feed = requests.get(f"{BASE}/api/feed?limit=5", timeout=15).json()
c3 = any("vault-rag验收冒烟" in e.get("path", "") for e in feed.get("events", []))
add("C 记忆心跳", "/api/feed 记忆流可见", c3,
    (feed["events"] or [{}])[0].get("path", "")[:50])

head = requests.get(f"{BASE}/api/headline", timeout=15).json()
c4 = head.get("latest") and "vault-rag验收冒烟" in head["latest"].get("path", "")
add("C 记忆心跳", "头条=最新代理动作", c4, (head.get("latest") or {}).get("path", "")[:50])
cli.close()
print()

# ============ D. MCP multimodal_search 指定错题 ============
print("═ D. MCP multimodal_search ═")
cli = McpClient(cfg["cmd"], cfg["cwd"])
cli.send({"jsonrpc": "2.0", "id": 1, "method": "initialize",
          "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                     "clientInfo": {"name": "acceptance", "version": "1.0"}}})
cli.wait_resp(1, 60)
cli.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
cli.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {
    "name": "multimodal_search",
    "arguments": {"query": "矩形的性质 折叠 30度", "top_k": 3}}})
resp = cli.wait_resp(2, 60)
content = "".join(c.get("text", "") for c in resp.get("result", {}).get("content", []))
d1 = "矩形的性质" in content
add("D MCP 多模态", "rag-obsidian 指定错题查询", d1, content[:70])
cli.close()
print()

# ============ E. 问答后端（OpenAI 兼容） ============
print("═ E. 问答后端 /v1/chat/completions ═")
key = requests.get(f"{BASE}/api/backend/info", timeout=10).json()["key"]
r = requests.post(f"{BASE}/v1/chat/completions",
                  headers={"Authorization": f"Bearer {key}"},
                  json={"messages": [{"role": "user",
                                      "content": "agent 怎么防遗忘？简述"}]},
                  timeout=120)
d = r.json()
ans = d["choices"][0]["message"]["content"]
srcs = d.get("vault_rag_sources", [])
add("E 问答后端", "OpenAI 兼容 200 + 回答", r.status_code == 200 and len(ans) > 30,
    f"回答 {len(ans)} 字 · 引用 {len(srcs)} 条")
add("E 问答后端", "引用来自知识库", len(srcs) > 0,
    (srcs[0]["rel_path"][:44] if srcs else "无"))
print()

# ============ 打分卡 ============
print("═"*62)
print("打分卡")
mods = {}
for mod, item, ok, note in card:
    mods.setdefault(mod, [0, 0])
    mods[mod][0] += ok == "✓"
    mods[mod][1] += 1
for mod, (okn, n) in mods.items():
    print(f"  {mod}: {okn}/{n}")
total_ok = sum(1 for *_, ok, _ in [(m, i, o, n) for m, i, o, n in card] if ok == "✓")
print(f"\n  总计 {total_ok}/{len(card)}")
Path(REPO / "data" / "_acceptance_card.json").write_text(
    json.dumps(card, ensure_ascii=False, indent=1), encoding="utf-8")
