# -*- coding: utf-8 -*-
"""vault-rag Web 控制台 — 检索问答（Agnes）+ 看板 + 内容管理。

用法：
    python webui.py                # pywebview 窗口（默认）
    python webui.py --browser      # 用默认浏览器打开
    python webui.py --server       # 只起服务不打开界面（调试/远程）
    RAG_WEBUI_PORT=8765            # 端口固定
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from vault_rag.config import WEBUI_HOST, WEBUI_PORT, VAULT
from vault_rag import webui_lib as lib

if getattr(sys, "frozen", False):
    ASSETS = Path(sys._MEIPASS) / "webui_assets"      # PyInstaller 解包目录
else:
    ASSETS = Path(__file__).resolve().parent.parent / "webui_assets"
REPO = Path(__file__).resolve().parent.parent

app = FastAPI(title="vault-rag 控制台", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ASSETS), name="static")
from vault_rag.webui_ext import router as ext_router  # noqa: E402
app.include_router(ext_router)

_EMBED_LOCK = threading.Lock()          # 查询编码串行化（10 线程上限下避免争抢）
_INDEX_LOCK = threading.Lock()          # 同一时间只允许一个索引进程（进程内）
_INDEX_STATE: dict = {"running": False, "started": 0.0, "finished": 0.0,
                      "log": "", "ok": None}
_WEBVIEW_WINDOW = None                  # pywebview 窗口引用（文件选择对话框用）


def _sse(obj: dict) -> str:
    import json
    return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"


# ---------------- 状态 / 看板 ----------------

@app.get("/")
def index():
    return FileResponse(ASSETS / "index.html")


@app.get("/api/status")
def api_status():
    st = lib.status()
    st["embed_ready"] = embed_endpoint_alive()
    try:
        from vault_rag.config import API_URL
        st["embed_url"] = API_URL
    except Exception:
        st["embed_url"] = ""
    return st


@app.get("/api/dashboard")
def api_dashboard():
    return lib.dashboard()


# ---------------- 检索 / 问答 ----------------

class SearchReq(BaseModel):
    q: str
    k: int = 8


@app.post("/api/search")
def api_search(req: SearchReq):
    if not req.q.strip():
        raise HTTPException(400, "查询为空")
    with _EMBED_LOCK:
        try:
            hits = lib.retrieve(req.q.strip(), top_k=req.k)
            mode = "semantic"
        except Exception:                    # 端点离线 → 关键词模式（静默，不算错误）
            hits = lib.keyword_fallback(req.q.strip(), top_k=req.k)
            mode = "keyword"
    return {"mode": mode, "results": [
        {"score": round(h["score"], 4), "rel_path": h["rel_path"],
         "section": h.get("section") or "", "text": h["text"][:300],
         "superseded": h.get("superseded", False)} for h in hits]}


class ChatReq(SearchReq):
    pass


@app.post("/api/chat")
def api_chat(req: ChatReq):
    """SSE：sources → delta* → done / error。Agnes 不可用时自动降级为纯检索。"""
    def gen():
        try:
            with _EMBED_LOCK:
                hits = lib.retrieve(req.q.strip(), top_k=req.k)
        except Exception:
            with _EMBED_LOCK:
                hits = lib.keyword_fallback(req.q.strip(), top_k=req.k)
            # 非错误：端点没开就安静用关键词，不吓唬人
            yield _sse({"type": "info",
                        "message": "当前为关键词检索 · 启动 LM Studio(1234) 后自动升级语义检索"})
        yield _sse({"type": "sources", "results": [
            {"score": round(h["score"], 4), "rel_path": h["rel_path"],
             "section": h.get("section") or "", "superseded": h.get("superseded", False)}
            for h in hits]})
        messages = lib.build_messages(req.q.strip(), hits)
        acc = []
        try:
            for delta in lib.stream_chat(messages):
                acc.append(delta)
                yield _sse({"type": "delta", "text": delta})
            yield _sse({"type": "done"})
        except lib.ChatUnavailable as e:
            if acc:                          # 已有部分输出，不再整体报错
                yield _sse({"type": "warning", "message": f"生成中断: {e}"})
                yield _sse({"type": "done"})
            else:
                yield _sse({"type": "fallback", "message": str(e), "results": [
                    {"rel_path": h["rel_path"], "section": h.get("section") or "",
                     "text": h["text"][:300], "score": round(h["score"], 4)}
                    for h in hits]})
        except Exception as e:
            yield _sse({"type": "error", "message": f"{type(e).__name__}: {e}"})
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


# ---------------- 内容管理 ----------------

@app.get("/api/scope")
def api_scope_get():
    return {"text": lib.read_scope_text(), "vault": str(VAULT)}


class ScopeReq(BaseModel):
    text: str


@app.post("/api/scope")
def api_scope_save(req: ScopeReq):
    errors = lib.save_scope_text(req.text)
    if errors:
        raise HTTPException(422, {"errors": errors})
    return {"ok": True}


class AddExternalReq(BaseModel):
    path: str
    alias: str = ""


@app.post("/api/scope/add-external")
def api_scope_add(req: AddExternalReq):
    ok, msg = lib.add_external_file(req.path, req.alias or None)
    return {"ok": ok, "message": msg}


class NoteReq(BaseModel):
    rel_path: str
    content: str = ""
    overwrite: bool = False


@app.post("/api/note")
def api_note_create(req: NoteReq):
    ok, msg = lib.create_note(req.rel_path, req.content, req.overwrite)
    return {"ok": ok, "message": msg}


@app.post("/api/open")
def api_open(req: dict):
    rel = str(req.get("rel_path", "")).strip()
    if not rel:
        raise HTTPException(400, "缺少 rel_path")
    target = (VAULT / rel)
    if not str(target.resolve()).startswith(str(VAULT.resolve())):
        raise HTTPException(400, "路径越出 vault")
    if not target.exists():
        raise HTTPException(404, f"文件不存在: {rel}")
    import os
    os.startfile(target)                    # Windows 默认程序（Obsidian/markdown）
    return {"ok": True}


@app.get("/api/pick-file")
def api_pick_file():
    """pywebview 原生文件对话框；浏览器模式返回 501 由前端提示手输路径。"""
    if _WEBVIEW_WINDOW is None:
        raise HTTPException(501, "仅桌面窗口模式支持文件选择，请直接粘贴路径")
    import webview
    files = _WEBVIEW_WINDOW.create_file_dialog(
        webview.OPEN_DIALOG, allow_multiple=False)
    if not files:
        return {"path": ""}
    return {"path": str(files[0]) if isinstance(files, list) else str(files)}


# ---------------- 设置 / 供应商（cc-switch 式切换） ----------------

@app.get("/api/settings")
def api_settings_get():
    prof = lib.active_provider()
    return {"key_set": lib.chat_ready(), "endpoint": prof["url"],
            "model": prof["model"], "provider": prof["name"]}


class SettingsReq(BaseModel):
    agnes_key: str = ""


@app.post("/api/settings")
def api_settings_save(req: SettingsReq):
    lib.save_local_settings({"agnes_key": req.agnes_key.strip()})
    return {"ok": True, "key_set": lib.chat_ready()}


@app.get("/api/providers")
def api_providers_get():
    return {"profiles": lib.chat_profiles(), "active": lib.active_provider()}


class ProviderReq(BaseModel):
    name: str = ""
    url: str = ""
    model: str = ""
    key: str = ""


@app.post("/api/providers")
def api_providers_switch(req: ProviderReq):
    try:
        prof = lib.switch_provider(req.name.strip() or None,
                                   req.url.strip() or None,
                                   req.model.strip() or None,
                                   key=req.key.strip() or None)
    except ValueError as e:
        raise HTTPException(422, str(e))
    return {"ok": True, "active": prof}


@app.delete("/api/providers")
def api_providers_delete(req: ProviderReq):
    try:
        return {"ok": True, **lib.delete_provider(req.name.strip())}
    except ValueError as e:
        raise HTTPException(422, str(e))


@app.post("/api/chat/test")
def api_chat_test():
    """当前供应商连通性测试（不计入对话）。"""
    return lib.test_provider()


# ---------------- 检索 Embedding 设置 ----------------

@app.get("/api/embed/config")
def api_embed_config():
    from vault_rag import search, embed_providers
    st = lib.load_local_settings().get("embed", {})
    return {
        "backend": st.get("backend", os.environ.get("RAG_EMBED_BACKEND", "auto")),
        "http_profiles": st.get("http_profiles") or [
            {"name": "LM Studio", "url": "http://127.0.0.1:1234/v1/embeddings",
             "model": "text-embedding-qwen3-embedding-0.6b"}],
        "http_active": st.get("http_active", "LM Studio"),
        "endpoint_alive": embed_endpoint_alive(),
        "llama": embed_providers.llama_available(),
        "ggufs": embed_providers.list_ggufs(),
        "hf_presets": embed_providers.HF_PRESETS,
        "dl": embed_providers.dl_status(),
    }


class EmbedConfigReq(BaseModel):
    backend: str = ""
    http_profiles: list = []
    http_active: str = ""


def _save_embed_config(patch: dict):
    st = lib.load_local_settings()
    merged = {**(st.get("embed") or {}), **patch}
    lib.save_local_settings({"embed": merged})
    from vault_rag import search
    search._EMBED_PROBE["t"] = 0.0            # 让活性探测立即重估


@app.post("/api/embed/config")
def api_embed_config_save(req: EmbedConfigReq):
    patch: dict = {}
    if req.backend:
        if req.backend not in ("auto", "http", "llamacpp", "off", "local"):
            raise HTTPException(422, f"未知模式: {req.backend}")
        patch["backend"] = req.backend
    if req.http_profiles:
        patch["http_profiles"] = req.http_profiles
    if req.http_active:
        patch["http_active"] = req.http_active
    _save_embed_config(patch)
    # HTTP 端点可配 → search 的 URL/模型也要跟着档案走
    st = lib.load_local_settings().get("embed") or {}
    profs = st.get("http_profiles") or []
    act = next((p for p in profs if p.get("name") == st.get("http_active")), profs[0] if profs else None)
    if act:
        os.environ["RAG_EMBED_HTTP_URL"] = act.get("url", "")
        os.environ["RAG_EMBED_HTTP_MODEL"] = act.get("model", "")
        from vault_rag import search
        search.EMBED_HTTP_URL = act.get("url", search.EMBED_HTTP_URL)
        search.EMBED_HTTP_MODEL = act.get("model", search.EMBED_HTTP_MODEL)
    return {"ok": True}


class GgufSelectReq(BaseModel):
    file: str


@app.post("/api/embed/gguf/select")
def api_embed_gguf_select(req: GgufSelectReq):
    from vault_rag import embed_providers
    if not (embed_providers.GGUF_DIR / req.file).exists():
        raise HTTPException(404, f"文件不存在: {req.file}")
    lib.save_local_settings({"llama_gguf": req.file})
    return {"ok": True, "active": req.file}


@app.get("/api/embed/hf/files")
def api_embed_hf_files(repo: str, mirror: bool = True):
    from vault_rag import embed_providers
    try:
        return {"ok": True, "files": embed_providers.hf_list_files(repo, mirror)}
    except Exception as e:
        raise HTTPException(502, f"拉取文件列表失败: {e}")


class HfDownloadReq(BaseModel):
    repo: str
    file: str
    mirror: bool = True


@app.post("/api/embed/hf/download")
def api_embed_hf_download(req: HfDownloadReq):
    from vault_rag import embed_providers
    return embed_providers.hf_download(req.repo, req.file, req.mirror)


@app.get("/api/embed/hf/status")
def api_embed_hf_status():
    from vault_rag import embed_providers
    return embed_providers.dl_status()


# ---------------- 索引管理 ----------------

@app.post("/api/index/refresh")
def api_index_refresh():
    if _INDEX_STATE["running"]:
        return {"ok": False, "message": "索引已在进行中"}
    if not _INDEX_LOCK.acquire(blocking=False):
        return {"ok": False, "message": "索引已在进行中"}
    _INDEX_STATE.update({"running": True, "started": time.time(),
                         "log": "", "ok": None})

    def worker():
        buf_out, buf_err = io.StringIO(), io.StringIO()
        _INDEX_STATE["buf_out"], _INDEX_STATE["buf_err"] = buf_out, buf_err
        ok = None
        try:
            from vault_rag import indexer_qwen
            with contextlib.redirect_stdout(buf_out), \
                    contextlib.redirect_stderr(buf_err):
                indexer_qwen.index()
            ok = True
        except Exception as e:
            buf_err.write(f"\n[fatal] {type(e).__name__}: {e}\n")
            traceback.print_exc(file=buf_err)
            ok = False
        finally:
            _INDEX_LOCK.release()            # 端点 acquire，worker 释放
            try:
                from vault_rag import search
                search._CACHE["stamp"] = None    # 索引变了，清向量缓存
            except Exception:
                pass                             # 收尾清理绝不阻塞状态落盘
            _INDEX_STATE.pop("buf_out", None)
            _INDEX_STATE.pop("buf_err", None)
            tail = "\n".join((buf_out.getvalue() + "\n" + buf_err.getvalue())
                             .strip().splitlines()[-30:])
            _INDEX_STATE.update({"running": False, "finished": time.time(),
                                 "ok": ok, "log": tail})
    threading.Thread(target=worker, name="index-worker", daemon=True).start()
    return {"ok": True, "message": "增量索引已启动（后台执行）"}


@app.get("/api/index/status")
def api_index_status():
    st = dict(_INDEX_STATE)
    if st["started"]:
        st["elapsed"] = round((st["finished"] or time.time()) - st["started"], 1)
    else:
        st["elapsed"] = 0
    if st["running"] and st.get("buf_out") is not None:      # 运行中实时日志
        live = (st.pop("buf_out").getvalue() + "\n" +
                st.pop("buf_err", io.StringIO()).getvalue())
        st["log"] = "\n".join(live.strip().splitlines()[-30:])
    st.pop("buf_out", None)
    st.pop("buf_err", None)
    st["pending"] = lib.pending_count()
    return st


# ---------------- 启动 ----------------

def _free_port(host: str, port: int) -> int:
    """优先用配置端口；被占则向后顺延找空闲（避免二开实例静默退出）。"""
    for p in range(port, port + 10):
        with socket.socket() as s:
            if s.connect_ex((host, p)) != 0:
                return p
    raise SystemExit(f"端口 {port}~{port+9} 均被占用（RAG_WEBUI_PORT 可指定）")


_EMBED_PROBE_LOCK = threading.Lock()


def embed_endpoint_alive() -> bool:
    """探测检索向量端点（search.py 内缓存 8 秒，状态轮询不重复打端点）。"""
    from vault_rag import search
    return search.embed_endpoint_alive()


def _apply_embed_settings():
    """把持久化的 Embedding 配置应用到 search 模块（后端模式 / HTTP 端点档案）。"""
    try:
        from vault_rag import search
        st = lib.load_local_settings().get("embed") or {}
        if st.get("backend"):
            search.EMBED_BACKEND = st["backend"]
        profs = st.get("http_profiles") or []
        act = next((p for p in profs if p.get("name") == st.get("http_active")),
                   profs[0] if profs else None)
        if act and act.get("url"):
            search.EMBED_HTTP_URL = act["url"]
            search.EMBED_HTTP_MODEL = act.get("model", search.EMBED_HTTP_MODEL)
    except Exception as e:
        print(f"[webui] 应用 Embedding 配置失败: {e}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="vault-rag Web 控制台")
    ap.add_argument("--browser", action="store_true", help="用系统浏览器打开")
    ap.add_argument("--server", action="store_true", help="只起服务，不打开界面")
    ap.add_argument("--port", type=int, default=WEBUI_PORT)
    args = ap.parse_args()

    # 打包态无控制台：sys.stdout/stderr 可能为 None（双击启动时），日志落到 data/webui.log
    if getattr(sys, "frozen", False) and (
            sys.stdout is None or sys.stderr is None or not sys.stdout.isatty()):
        from vault_rag.config import DATA_DIR
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        log_f = open(DATA_DIR / "webui.log", "a", encoding="utf-8", buffering=1)
        sys.stdout = log_f
        sys.stderr = log_f

    port = _free_port(WEBUI_HOST, args.port)
    url = f"http://{WEBUI_HOST}:{port}"
    config = uvicorn.Config(app, host=WEBUI_HOST, port=port, log_level="warning",
                            workers=1, access_log=False)
    server = uvicorn.Server(config)
    threading.Thread(target=server.run, daemon=True).start()
    for _ in range(50):                      # 等服务就绪
        with socket.socket() as s:
            if s.connect_ex((WEBUI_HOST, port)) == 0:
                break
        time.sleep(0.1)
    # 查询侧零模型加载（向量走 HTTP 端点/内置 llama.cpp）；torch 仅增量索引时按需加载
    _apply_embed_settings()

    if args.server:
        print(f"[webui] 服务运行中 {url} （Ctrl+C 退出）")
        try:
            while server.started:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        return

    global _WEBVIEW_WINDOW
    try:
        import webview
        _WEBVIEW_WINDOW = webview.create_window(
            "vault-rag 控制台", url, width=1280, height=860, min_size=(960, 640))
        webview.start()
    except Exception as e:
        print(f"[webview] 窗口不可用（{e}），改用浏览器模式")
        webbrowser.open(url)
        try:
            while server.started:
                time.sleep(1)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:                  # 窗口态没有控制台，致命错误弹原生框
        if getattr(sys, "frozen", False):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, str(e), "vault-rag 控制台", 0x10)
        raise
