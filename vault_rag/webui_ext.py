# -*- coding: utf-8 -*-
"""webui_ext.py — 控制台扩展路由：RAG 仓库管理 / 系统自检 / 用户偏好。"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Body
from pydantic import BaseModel

from vault_rag import repo_admin, selftest, webui_lib as lib

router = APIRouter(prefix="/api", tags=["repo/selftest/prefs"])


# ---------------- RAG 仓库管理 ----------------

@router.get("/repo/notes")
def repo_notes(q: str = "", domain: str = "", page: int = 1, size: int = 30):
    return repo_admin.notes_page(q=q, domain=domain, page=page, size=size)


@router.get("/repo/stats")
def repo_stats():
    return repo_admin.stats()


class RepoNoteReq(BaseModel):
    rel_path: str


@router.delete("/repo/notes")
def repo_note_delete(req: RepoNoteReq):
    try:
        return {"ok": True, **repo_admin.delete_note(req.rel_path)}
    except ValueError as e:
        raise HTTPException(404, str(e))


@router.post("/repo/clear-cache")
def repo_clear_cache():
    return {"ok": True, **repo_admin.clear_cache()}


@router.post("/repo/vacuum")
def repo_vacuum():
    return {"ok": True, **repo_admin.vacuum()}


@router.post("/repo/rebuild")
def repo_rebuild():
    """全量重建第一步：清空索引（KV 缓存保留）。随后调用 /api/index/refresh。"""
    return repo_admin.rebuild_all()


# ---------------- 系统自检（沿 MCP 同步链路） ----------------

@router.get("/selftest")
def api_selftest():
    return selftest.run_selftest()


# ---------------- 用户偏好 ----------------

@router.get("/prefs")
def prefs_get():
    return lib.load_local_settings().get("prefs") or {
        "temperature": 0.3, "top_k": 6, "context_chars": 600}


class PrefsReq(BaseModel):
    temperature: float | None = None
    top_k: int | None = None
    context_chars: int | None = None


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
    return {"ok": True, "prefs": prefs}
