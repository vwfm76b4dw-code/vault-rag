# -*- coding: utf-8 -*-
"""webui_ext.py — 控制台扩展路由：仓库管理 / 上传 / 系统自检 / 用户偏好 / MCP&状态。"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File
from pydantic import BaseModel

from vault_rag import repo_admin, selftest, webui_lib as lib
from vault_rag.config import DATA_DIR

router = APIRouter(prefix="/api", tags=["repo/selftest/prefs/mcp"])

UPLOAD_DIR = DATA_DIR / "uploads"


# ---------------- RAG 仓库管理（多仓库） ----------------

@router.get("/repos")
def repos_list():
    from vault_rag import repos as R
    return {"ok": True, "current": R.current_data_dir(), "repos": R.discover()}


class RepoCreateReq(BaseModel):
    name: str
    data_dir: str = ""


@router.post("/repos/create")
def repos_create(req: RepoCreateReq):
    name = req.name.strip()
    if not name or any(c in name for c in '\\/:*?"<>|'):
        raise HTTPException(422, "仓库名非法（禁止 \\/:*?\"<>|）")
    from vault_rag import repos as R
    if any(r["name"] == name for r in R.load_registry()):
        raise HTTPException(422, f"仓库名已存在: {name}")
    prof = R.create_repo(name, req.data_dir.strip() or None)
    R.switch_to(name)                     # 新建即切换（与按钮文案一致）
    return {"ok": True, **prof}


class RepoSwitchReq(BaseModel):
    name: str


@router.post("/repos/switch")
def repos_switch(req: RepoSwitchReq):
    from vault_rag import repos as R
    try:
        prof = R.switch_to(req.name.strip())
    except ValueError as e:
        raise HTTPException(422, str(e))
    # 切换后向量化缓存已失效；提示前端刷新数据
    return {"ok": True, "active": prof, "message": "已切换（立即生效；独立 MCP 进程重启后跟随）"}


# ---------------- 批量上传（多文件 → data/uploads + 自动 @ 规则） ----------------

@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """批量上传文档：存 data/uploads/<批次>/ 并自动加入索引范围（@ 规则）。"""
    if not files:
        raise HTTPException(400, "未选择文件")
    batch = UPLOAD_DIR / time.strftime("%Y%m%d-%H%M%S")
    batch.mkdir(parents=True, exist_ok=True)
    saved, skipped = [], []
    for f in files:
        safe = Path(f.filename).name
        if not safe or safe.startswith("."):
            skipped.append(safe or "(空名)")
            continue
        dest = batch / safe
        with open(dest, "wb") as out:
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        ok, msg = lib.add_external_file(str(dest), alias=f"external/{safe}")
        (saved if ok else skipped).append(f"{safe} ({msg})" if not ok else safe)
    return {"ok": True, "batch_dir": str(batch),
            "saved": saved, "skipped": skipped,
            "message": f"已上传 {len(saved)} 个文件并加入范围，执行增量索引后可检索"}


# ---------------- 系统自检 ----------------

@router.get("/selftest")
def api_selftest():
    return selftest.run_selftest()


# ---------------- 用户偏好 ----------------

@router.get("/prefs")
def prefs_get():
    p = lib.load_local_settings().get("prefs") or {}
    return {"temperature": p.get("temperature", 0.3), "top_k": p.get("top_k", 6),
            "threads": p.get("threads", 16), "context_chars": p.get("context_chars", 600)}


class PrefsReq(BaseModel):
    temperature: float | None = None
    top_k: int | None = None
    context_chars: int | None = None
    threads: int | None = None


def _apply_threads(n: int) -> None:
    """线程数运行时生效:环境变量 + config + 已加载的 torch。"""
    import os as _os
    n = max(1, min(32, int(n)))
    prefs = {**(lib.load_local_settings().get("prefs") or {}), "threads": n}
    lib.save_local_settings({"prefs": prefs})
    _os.environ["RAG_TORCH_THREADS"] = str(n)
    import vault_rag.config as config
    config.TORCH_THREADS = n
    try:
        import torch
        torch.set_num_threads(n)
    except Exception:
        pass


@router.post("/prefs")
def prefs_save(req: PrefsReq):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    if "temperature" in patch:
        patch["temperature"] = max(0.0, min(2.0, float(patch["temperature"])))
    if "top_k" in patch:
        patch["top_k"] = max(1, min(30, int(patch["top_k"])))
    if "context_chars" in patch:
        patch["context_chars"] = max(200, min(2000, int(patch["context_chars"])))
    prefs = {**(lib.load_local_settings().get("prefs") or {}), **patch}
    lib.save_local_settings({"prefs": prefs})
    if "threads" in patch:
        _apply_threads(int(patch["threads"]))
    return {"ok": True, "prefs": prefs}


# ---------------- MCP & 状态 ----------------

def _claude_mcp_servers() -> dict:
    p = Path.home() / ".claude.json"
    try:
        return (json.loads(p.read_text(encoding="utf-8"))
                .get("mcpServers") or {})
    except Exception:
        return {}


@router.get("/mcp/status")
def mcp_status():
    servers = _claude_mcp_servers()
    rag_obs = Path.home() / ".claude/mcp_servers/rag-obsidian/server.py"
    out = []
    for name in ("rag-obsidian", "obsidian-search", "vault-rag"):
        entry = servers.get(name)
        out.append({
            "name": name,
            "registered": entry is not None,
            "cmd": (entry or {}).get("command", ""),
            "args": " ".join((entry or {}).get("args", [])),
        })
    return {
        "servers": out,
        "rag_obsidian_server": str(rag_obs),
        "rag_obsidian_exists": rag_obs.exists(),
        "hint": "vault-rag 未注册时，复制下方注册命令到 Claude Code 配置即可",
    }


@router.post("/mcp/register-vaultrag")
def mcp_register_vaultrag():
    """把 vault_rag.rag_mcp 注册进 Claude Code（~/.claude.json）。"""
    import json as _json
    p = Path.home() / ".claude.json"
    try:
        cfg = _json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        cfg = {}
    entry = {"command": sys_executable(),
             "args": [str(Path(__file__).resolve().parent.parent / "rag_mcp_server.py")]}
    cfg.setdefault("mcpServers", {})["vault-rag"] = entry
    backup = p.with_suffix(".json.bak")
    backup.write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    p.write_text(_json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"ok": True, "entry": entry, "backup": str(backup)}


def sys_executable() -> str:
    import sys
    return sys.executable


@router.get("/mcp/clients")
def mcp_clients_list():
    from vault_rag import mcp_clients as MC
    return {"ok": True,
            "clients": [dict(MC.detect(c), snippet=MC.snippet(c)) for c in MC.CLIENTS]}


class ClientRegReq(BaseModel):
    client: str


@router.post("/mcp/clients/register")
def mcp_clients_register(req: ClientRegReq):
    from vault_rag import mcp_clients as MC
    c = next((x for x in MC.CLIENTS if x["id"] == req.client), None)
    if not c:
        raise HTTPException(422, f"未知客户端: {req.client}")
    try:
        return {"ok": True, **MC.register(c)}
    except Exception as e:
        raise HTTPException(500, f"{type(e).__name__}: {e}")


@router.post("/mcp/protocol-test")
def mcp_protocol_test(server: str = "rag"):
    """实时协议级探测（initialize + tools/list，不走模型）。"""
    import subprocess
    import sys as _sys
    if server == "rag":
        cmd = [_sys.executable, "-m", "vault_rag.rag_mcp"]
        cwd = str(Path(__file__).resolve().parent.parent)
        expect = ["semantic_search", "rag_status"]
    elif server == "obsidian":
        srv = Path.home() / ".claude/mcp_servers/rag-obsidian/server.py"
        if not srv.exists():
            return {"ok": False, "detail": "server.py 不存在"}
        cmd = [_sys.executable, str(srv)]
        cwd = str(srv.parent)
        expect = ["semantic_search"]
    else:
        raise HTTPException(422, "未知 server")
    try:
        from vault_rag import mcp_probe
        result = mcp_probe.quick_probe(cmd, cwd, expect)
        return result
    except Exception as e:
        return {"ok": False, "detail": f"{type(e).__name__}: {e}"}
