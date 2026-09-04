# -*- coding: utf-8 -*-
"""webui_ext.py — 控制台扩展路由：仓库管理 / 上传 / 系统自检 / 用户偏好 / MCP&状态。"""
from __future__ import annotations

import json
import threading
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


# ---------------- 仓库页：索引统计 / 笔记浏览 / 库操作 ----------------
# 前端 app.js 的仓库管理页（loadRepo/renderRepo/库操作按钮）依赖以下端点，
# v1.2.0 IA 重构时漏接（repo_admin 函数早已就绪）→ 404 静默坏页。

@router.get("/repo/stats")
def repo_stats():
    return repo_admin.stats()


@router.get("/repo/notes")
def repo_notes(q: str = "", domain: str = "", page: int = 1, size: int = 15):
    return repo_admin.notes_page(q=q.strip(), domain=domain.strip(),
                                 page=max(1, page), size=max(1, min(100, size)))


class RepoNoteDelReq(BaseModel):
    rel_path: str


@router.delete("/repo/notes")
def repo_note_delete(req: RepoNoteDelReq):
    try:
        return repo_admin.delete_note(req.rel_path)
    except ValueError as e:
        raise HTTPException(422, str(e))


@router.post("/repo/clear-cache")
def repo_clear_cache():
    return repo_admin.clear_cache()


@router.post("/repo/vacuum")
def repo_vacuum():
    return repo_admin.vacuum()


@router.post("/repo/rebuild")
def repo_rebuild():
    return repo_admin.rebuild_all()


# ---------------- 批量上传（多文件 → data/uploads + 自动 @ 规则） ----------------

# 图像/二进制检测：扩展名优先，magic bytes 兜底（防止改名 .txt 的图片静默入库）
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".ico", ".tif", ".tiff", ".heic", ".avif"}
DOC_EXTS = {".pdf", ".pptx"}          # 多模态管线一键处理（视觉拆页）
_IMAGE_MAGIC = (b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a",
                b"\x00\x00\x01\x00")          # PNG/JPEG/GIF/ICO
_BINARY_MAGIC = (b"%PDF", b"PK\x03\x04", b"\x1f\x8b", b"MZ",
                 b"\x7fELF")                  # PDF/ZIP/GZIP/EXE/ELF
IMAGE_HINT = "图片暂不支持索引（多模态索引规划中），已跳过"


def classify_upload(filename: str, head: bytes) -> str:
    """按扩展名 + magic bytes 判定上传类型：'image' / 'binary' / 'doc' / 'mismatch' / 'text'。

    文本误杀防线：只认强 magic 与 NUL 字节，不用 "BM"/"RIFF" 这类
    与 ASCII 文本重叠的前缀（"BMW 开头的笔记" 不能被当二进制）。
    doc 类型必须验 magic：假扩展名（文本改 .pdf/.pptx）会在拆页管线深处才炸。
    """
    ext = Path(filename).suffix.lower()
    if ext in IMAGE_EXTS:
        return "image"
    if ext in DOC_EXTS:
        ok_pdf = head.startswith(b"%PDF-")
        ok_pptx = head.startswith(b"PK\x03\x04")
        if (ext == ".pdf" and ok_pdf) or (ext == ".pptx" and ok_pptx):
            return "doc"
        return "mismatch"
    if head.startswith(_IMAGE_MAGIC):
        return "image"
    if head.startswith(_BINARY_MAGIC) or b"\x00" in head:
        return "binary"
    return "text"


@router.post("/upload")
async def upload_files(files: list[UploadFile] = File(...)):
    """批量上传文档：存 data/uploads/<批次>/ 并自动加入索引范围（@ 规则）。

    图像/二进制文件显式拒绝并说明原因——绝不允许静默入库后索引黑洞。
    """
    if not files:
        raise HTTPException(400, "未选择文件")
    batch = UPLOAD_DIR / time.strftime("%Y%m%d-%H%M%S")
    saved, skipped, mm_files = [], [], []
    for f in files:
        safe = Path(f.filename).name
        if not safe or safe.startswith("."):
            skipped.append(f"{safe or '(空名)'} (非法文件名)")
            continue
        head = await f.read(1 << 16)
        kind = classify_upload(safe, head)
        if kind in ("image", "binary"):
            reason = IMAGE_HINT if kind == "image" else "二进制文件暂不支持索引，已跳过"
            skipped.append(f"{safe} ({reason})")
            continue
        if kind == "mismatch":
            skipped.append(f"{safe} (扩展名与内容不符——不是有效的 PDF/PPTX，已跳过)")
            continue
        batch.mkdir(parents=True, exist_ok=True)
        dest = batch / safe
        with open(dest, "wb") as out:
            out.write(head)
            while chunk := await f.read(1 << 20):
                out.write(chunk)
        if kind == "doc":
            # PDF/PPTX → 多模态一键管线（前端拿到 mm_files 后调 /api/mm/ingest）
            mm_files.append(str(dest))
            saved.append(f"{safe} (多模态待处理)")
            continue
        ok, msg = lib.add_external_file(str(dest), alias=f"external/{safe}")
        (saved if ok else skipped).append(f"{safe} ({msg})" if not ok else safe)
    n_skip = len(skipped)
    if saved:
        message = (f"已入库 {len(saved)} 个文件，执行增量索引后可检索"
                   + (f"；跳过 {n_skip} 个不支持的文件" if n_skip else ""))
    else:
        message = "没有文件入库" + (f"（{n_skip} 个均不支持）" if n_skip else "")
    return {"ok": bool(saved), "batch_dir": str(batch) if saved else "",
            "saved": saved, "skipped": skipped, "message": message,
            "mm_files": mm_files}


# ---------------- 错题本（灵魂功能：拍照 → 结构化 → 可检索可复习） ----------------

@router.post("/mistake/ingest")
async def mistake_ingest(file: UploadFile = File(...)):
    """图片拖入上传页自动路由到这里：视觉识别批改 → 生成错题笔记 → vault/错题/。"""
    import uuid
    from vault_rag import mistake as M
    from vault_rag.config import VAULT
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "空文件")
    kind = classify_upload(file.filename or "", raw[:1 << 16])
    if kind == "binary":
        raise HTTPException(422, "这不是图片，请走文档上传")
    # 原图留档（data/uploads/ 不占 include 规则，笔记才是检索主体）
    keep = UPLOAD_DIR / time.strftime("%Y%m%d-%H%M%S") / f"mistake-{uuid.uuid4().hex[:6]}-{Path(file.filename or 'photo.png').name}"
    keep.parent.mkdir(parents=True, exist_ok=True)
    keep.write_bytes(raw)
    try:
        note_path, preview = M.ingest(raw, keep.name)
    except M.MistakeError as e:
        raise HTTPException(422, str(e))
    except Exception as e:
        name = type(e).__name__
        raise HTTPException(502, f"视觉识别失败（{name}）：{e}。"
                              f"请在「模型·生成供应商」选择支持图像输入的档案。")
    rel = note_path.relative_to(VAULT).as_posix()
    return {"ok": True, "note_rel": rel,
            "preview": preview,
            "message": f"错题已入库：{rel}（明日进入复习队列）"}


# ---------------- 记忆流 + 报纸头条（共享大脑的心跳） ----------------

@router.get("/feed")
def feed(limit: int = 50):
    """代理活动记忆流：MCP 写入事件倒序。"""
    from vault_rag import agent_feed
    return {"events": agent_feed.tail(limit=max(1, min(200, limit)))}


@router.get("/headline")
def headline():
    """报纸头条：最新代理动作 + 近 7 天新入库 + 今日到期错题。"""
    import time as _time
    from vault_rag import agent_feed, mistake as M
    from vault_rag import config as _cfg
    evts = agent_feed.tail(limit=20)
    latest = evts[0] if evts else None
    recent_notes, new_7d = [], 0
    try:
        week_ago = _time.time() - 7 * 86400
        con = repo_admin._con(readonly=True)
        try:
            new_7d = con.execute(
                "SELECT COUNT(*) FROM notes WHERE mtime >= ?",
                (week_ago,)).fetchone()[0]
            recent = con.execute(
                "SELECT rel_path FROM notes WHERE mtime >= ? "
                "ORDER BY mtime DESC LIMIT 5", (week_ago,)).fetchall()
            recent_notes = [r["rel_path"] for r in recent]
        finally:
            con.close()
    except Exception:
        pass
    due = M.due_reviews(vault=_cfg.VAULT, limit=6)
    return {"latest": latest, "feed": evts[:6], "new_7d": new_7d,
            "recent_notes": recent_notes, "due_reviews": due,
            "date": _time.strftime("%Y-%m-%d %A")}


# ---------------- 多模态一键处理（PDF/PPTX 识图） ----------------

class MmIngestReq(BaseModel):
    path: str
    strategy: str | None = None


@router.post("/mm/ingest")
def mm_ingest(req: MmIngestReq):
    """一键处理 PDF/PPTX：后台线程拆页→按策略入库，进度走 /api/mm/status。"""
    from vault_rag.multimodal import pipeline
    p = Path(req.path)
    if p.suffix.lower() not in (".pdf", ".pptx") or not p.exists():
        raise HTTPException(422, "仅支持已上传的 pdf/pptx 文件")
    head = p.open("rb").read(8)
    if p.suffix.lower() == ".pdf" and not head.startswith(b"%PDF-"):
        raise HTTPException(422, f"{p.name} 不是有效 PDF（文件头不符）")
    if p.suffix.lower() == ".pptx" and not head.startswith(b"PK\x03\x04"):
        raise HTTPException(422, f"{p.name} 不是有效 PPTX（文件头不符）")
    # 廉价探开：魔数合法但内容损坏的文件当场拒绝（否则后台管线深处才炸）
    try:
        if p.suffix.lower() == ".pdf":
            import pypdfium2 as pdfium
            doc = pdfium.PdfDocument(str(p))
            doc.close()
        else:
            import zipfile
            zipfile.ZipFile(p).close()
    except Exception as e:
        raise HTTPException(422, f"{p.name} 无法解析（{type(e).__name__}: {e}）")
    pipeline.state.update(running=False, ok=None, file="", total=0, done=0,
                          log="")     # 清残留状态，前端轮询据此识别"未启动"
    pipeline.ingest_async(str(p), req.strategy)
    return {"ok": True, "started": p.name,
            "strategy": req.strategy or pipeline.current_strategy()}


@router.get("/mm/status")
def mm_status():
    from vault_rag.multimodal import pipeline, store
    return {**{k: pipeline.state[k] for k in
               ("running", "file", "page", "total", "done", "ok", "log")},
            "stats": store.stats(),
            "strategy": pipeline.current_strategy()}


@router.get("/mm/strategy")
def mm_strategy_get():
    from vault_rag.multimodal import pipeline
    return {"strategy": pipeline.current_strategy(),
            "options": list(pipeline.STRATEGIES)}


class MmStrategyReq(BaseModel):
    strategy: str


@router.post("/mm/strategy")
def mm_strategy_set(req: MmStrategyReq):
    from vault_rag.multimodal import pipeline
    try:
        pipeline.set_strategy(req.strategy)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "strategy": req.strategy}


@router.get("/mm/prices")
def mm_prices(pages: int = 100):
    """三策略成本估算（models.dev 实时价，cc-switch 同源）。"""
    from vault_rag.multimodal import prices
    est = prices.estimate(pages)
    return {"estimate": est, "models": prices.vision_models()[:12],
            "source": "models.dev（cc-switch 价格面板同源，缓存 7 天）"}


class MmNoteReq(BaseModel):
    chunk_id: int


@router.post("/mm/to-note")
def mm_to_note(req: MmNoteReq):
    """命中转笔记：把某页描述/复盘写成 vault/资料/ 下的 md，可编辑可索引。"""
    from vault_rag.multimodal import store
    from vault_rag.config import VAULT
    ch = store.get_chunk(req.chunk_id)
    if not ch:
        raise HTTPException(404, "块不存在")
    stem = Path(ch["src"]).stem
    name = f"{stem}-p{ch['page']}.md"
    target = VAULT / "资料" / name
    target.parent.mkdir(parents=True, exist_ok=True)
    body = (f"---\nsource: {ch['src']}\npage: {ch['page']}\n"
            f"created: {time.strftime('%Y-%m-%d')}\n---\n\n"
            f"# {stem} · 第{ch['page']}页\n\n{ch['text'] or '（无文字）'}\n\n"
            f"[打开原文件]({ch['src'].replace(chr(92), '/')})\n")
    target.write_text(body, encoding="utf-8")
    return {"ok": True, "note": str(target)}


@router.post("/mm/calibrate")
def mm_calibrate():
    """一次性识图校准：后台跑 4 合成案例，结果写 local_settings（mm_calib）。"""
    from vault_rag.multimodal import pipeline
    if pipeline.state.get("calibrating"):
        raise HTTPException(409, "校准进行中")
    pipeline.state["calibrating"] = True

    def _run():
        try:
            pipeline.calibrate()
        finally:
            pipeline.state["calibrating"] = False
    threading.Thread(target=_run, daemon=True, name="mm-calib").start()
    return {"ok": True, "started": True}


@router.get("/mm/calibrate")
def mm_calibrate_get():
    from vault_rag.multimodal import pipeline
    lib_settings = lib.load_local_settings()
    return {"calibrating": pipeline.state.get("calibrating", False),
            "result": lib_settings.get("mm_calib")}


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
