# -*- coding: utf-8 -*-
"""webui_lib.py — Web 控制台后端逻辑（可独立单测，不起服务器）。

聊天生成走 OpenAI 兼容端点（默认 Agnes；也可指向 llama.cpp server 等本地端点，
见 config.CHAT_API_URL）。检索复用 search.py 的本地 embedding + 向量缓存。
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime
from pathlib import Path

import requests

from config import (CHAT_API_KEY_ENVS, CHAT_API_URL, CHAT_MODEL, CHAT_TIMEOUT,
                    DB_PATH, DATA_DIR, FTS_DB, LOCAL_SETTINGS_PATH, RELATIONS_DB,
                    VAULT, WEIGHTS_DB)
import scope as scopes

# ---------- 本地设置（key 等敏感项，gitignored） ----------

def load_local_settings() -> dict:
    try:
        return json.loads(LOCAL_SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_local_settings(patch: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    merged = {**load_local_settings(), **{k: v for k, v in patch.items() if v is not None}}
    LOCAL_SETTINGS_PATH.write_text(json.dumps(merged, ensure_ascii=False, indent=2),
                                   encoding="utf-8")


def chat_api_key() -> str:
    for env in CHAT_API_KEY_ENVS:
        v = os.environ.get(env)
        if v:
            return v
    return str(load_local_settings().get("agnes_key") or "")


def chat_ready() -> bool:
    return bool(chat_api_key())


# ---------- 供应商档案（cc-switch 式切换）----------

PROVIDER_PRESETS = [
    {"name": "Agnes 国内", "url": "https://api.agnes-ai.cn/v1/chat/completions",
     "model": "agnes-2.5-flash"},
    {"name": "Agnes 国际", "url": "https://apihub.agnes-ai.com/v1/chat/completions",
     "model": "agnes-2.5-flash"},
    {"name": "llama.cpp 本地", "url": "http://127.0.0.1:8080/v1/chat/completions",
     "model": "qwen3"},
]


def active_provider() -> dict:
    """当前生效的生成供应商（存 _local_settings.json，改完即时生效）。"""
    s = load_local_settings()
    cur = s.get("provider")
    if isinstance(cur, dict) and cur.get("url"):
        return {"name": str(cur.get("name", "自定义")),
                "url": str(cur["url"]), "model": str(cur.get("model", ""))}
    for p in PROVIDER_PRESETS:
        if p["name"] == cur:
            return dict(p)
    return dict(PROVIDER_PRESETS[0])            # 默认国内站


def switch_provider(name: str | None = None, url: str | None = None,
                    model: str | None = None) -> dict:
    """按预设名切换，或写入自定义 url/model。返回生效档案。"""
    if name:
        for p in PROVIDER_PRESETS:
            if p["name"] == name:
                save_local_settings({"provider": dict(p)})
                return dict(p)
        raise ValueError(f"未知供应商: {name}")
    if not url:
        raise ValueError("需要 name 或 url")
    prof = {"name": name or "自定义", "url": url, "model": model or ""}
    save_local_settings({"provider": prof})
    return prof


# ---------- 聊天提示词组装（纯函数） ----------

def build_context_block(chunks: list[dict], max_chars: int = 600) -> str:
    parts = []
    for i, c in enumerate(chunks, 1):
        warn = "（注意：该文档已被更新版本取代，仅供历史参考）" if c.get("superseded") else ""
        text = re.sub(r"\s+", " ", c["text"]).strip()[:max_chars]
        parts.append(f"[{i}] {c['rel_path']} :: {c['section'] or '正文'}{warn}\n{text}")
    return "\n\n".join(parts)


def build_messages(query: str, chunks: list[dict]) -> list[dict]:
    system = (
        "你是个人 Obsidian 知识库的问答助手。只依据给出的笔记片段回答用户问题；"
        "引用时用 [编号] 标注来源片段；片段不足以回答时明确说明，并给出最相关的线索；"
        "用简体中文，简洁、信息密度高。"
    )
    if not chunks:
        return [{"role": "system", "content": system},
                {"role": "user", "content": f"知识库中未检索到相关片段。\n\n问题：{query}\n"
                                            "请说明未找到相关笔记，并给出 2~3 条检索建议。"}]
    user = (f"知识库检索到的笔记片段：\n\n{build_context_block(chunks)}\n\n"
            f"用户问题：{query}")
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


# ---------- Agnes / OpenAI 兼容端点 ----------

class ChatUnavailable(Exception):
    pass


def stream_chat(messages: list[dict], temperature: float = 0.3):
    """流式生成，逐段 yield 文本增量。失败抛 ChatUnavailable。走当前生效供应商。"""
    key = chat_api_key()
    if not key:
        raise ChatUnavailable("未配置 API key（设置面板可填，或设 AGNES_API_KEY 环境变量）")
    prof = active_provider()
    try:
        r = requests.post(
            prof["url"],
            headers={"Authorization": f"Bearer {key}"},
            json={"model": prof["model"], "messages": messages,
                  "temperature": temperature, "stream": True},
            stream=True, timeout=(15, CHAT_TIMEOUT))
        if r.status_code != 200:
            raise ChatUnavailable(f"端点 HTTP {r.status_code}: {r.text[:120]}")
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                delta = json.loads(payload)["choices"][0]["delta"].get("content")
            except Exception:
                continue
            if delta:
                yield delta
    except ChatUnavailable:
        raise
    except requests.RequestException as e:
        raise ChatUnavailable(f"端点连接失败: {e}") from e


def chat_once(messages: list[dict], temperature: float = 0.3) -> str:
    """非流式兜底。"""
    key = chat_api_key()
    if not key:
        raise ChatUnavailable("未配置 API key")
    prof = active_provider()
    r = requests.post(
        prof["url"],
        headers={"Authorization": f"Bearer {key}"},
        json={"model": prof["model"], "messages": messages, "temperature": temperature},
        timeout=(15, CHAT_TIMEOUT))
    if r.status_code != 200:
        raise ChatUnavailable(f"端点 HTTP {r.status_code}: {r.text[:120]}")
    return r.json()["choices"][0]["message"]["content"]


def test_provider(timeout: float = 15.0) -> dict:
    """连通性测试：不发流，问一声"ping"。返回 {ok, latency_ms, detail}。"""
    t0 = time.time()
    try:
        chat_once([{"role": "user", "content": "ping，请只回复:pong"}], temperature=0)
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000), "detail": "连通"}
    except ChatUnavailable as e:
        return {"ok": False, "latency_ms": int((time.time() - t0) * 1000), "detail": str(e)}


# ---------- 检索 ----------

def retrieve(query: str, top_k: int = 6) -> list[dict]:
    """语义检索 + 被取代标记。embedding 模型不可用时抛异常由调用方处理。"""
    from search import search as _search
    hits = _search(query, top_k=top_k)
    superseded = superseded_paths()
    for h in hits:
        h["superseded"] = h["rel_path"] in superseded
    return hits


def keyword_fallback(query: str, top_k: int = 6) -> list[dict]:
    """embedding 不可用时的关键词兜底（LIKE 命中计数排序）。"""
    terms = [t for t in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", query)]
    if not terms:
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        where = " AND ".join("text LIKE ?" for _ in terms)
        rows = con.execute(
            f"SELECT rel_path, section, text FROM chunks WHERE {where} LIMIT 200",
            [f"%{t}%" for t in terms]).fetchall()
        scored = []
        for r in rows:
            t = r["text"]
            scored.append({"rel_path": r["rel_path"], "section": r["section"] or "",
                           "text": t, "score": sum(1 for x in terms if x in t) / len(terms),
                           "superseded": False})
        scored.sort(key=lambda x: -x["score"])
        seen, out = set(), []
        for s in scored:
            if s["rel_path"] in seen:
                continue
            seen.add(s["rel_path"])
            out.append(s)
            if len(out) >= top_k:
                break
        return out
    finally:
        con.close()


# ---------- 关系/时效 ----------

def superseded_paths() -> set[str]:
    if not RELATIONS_DB.exists():
        return set()
    try:
        con = sqlite3.connect(f"file:{RELATIONS_DB}?mode=ro", uri=True)
        out = {d for (d,) in con.execute("SELECT dst FROM edges WHERE kind='supersedes'")}
        con.close()
        return out
    except sqlite3.Error:
        return set()


# ---------- 看板 ----------

def _db_size_mb(p: Path) -> float:
    try:
        return p.stat().st_size / 1024 / 1024
    except OSError:
        return 0.0


def status() -> dict:
    """首页顶部状态条。"""
    con = sqlite3.connect(DB_PATH)
    try:
        notes = con.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        chunks = con.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        vectors = con.execute("SELECT COUNT(*) FROM blob_vectors").fetchone()[0]
        cache = con.execute("SELECT COUNT(*) FROM embed_cache").fetchone()[0]
        try:
            meta = dict(con.execute("SELECT key, value FROM meta").fetchall())
        except sqlite3.OperationalError:
            meta = {}
    except sqlite3.OperationalError:
        notes = chunks = vectors = cache = 0
        meta = {}
    finally:
        con.close()
    return {
        "vault": str(VAULT),
        "notes": notes, "chunks": chunks, "vectors": vectors,
        "embed_cache": cache,
        "consistent": chunks == vectors and chunks > 0,
        "db_mb": round(_db_size_mb(DB_PATH), 1),
        "last_indexed": meta.get("indexed_at") or datetime.fromtimestamp(
            DB_PATH.stat().st_mtime).strftime("%Y-%m-%d %H:%M") if DB_PATH.exists() else "—",
        "chat_ready": chat_ready(),
        "chat_model": CHAT_MODEL,
        "chat_endpoint": CHAT_API_URL,
        "relations_built": RELATIONS_DB.exists(),
        "weights_built": WEIGHTS_DB.exists(),
        "fts_linked": FTS_DB.exists(),
    }


def dashboard() -> dict:
    """看板页数据：领域分布 / 最近笔记 / 关系图 / 权重榜 / 待索引。"""
    domains, recent = [], []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        rows = con.execute(
            "SELECT CASE WHEN instr(rel_path,'/')>0 THEN substr(rel_path,1,instr(rel_path,'/')-1) "
            "ELSE '(根级)' END AS domain, COUNT(*) AS notes, SUM(n_chunks) AS chunks "
            "FROM notes GROUP BY domain ORDER BY notes DESC LIMIT 12").fetchall()
        domains = [dict(r) for r in rows]
        recent = [dict(r) for r in con.execute(
            "SELECT rel_path, n_chunks, mtime FROM notes ORDER BY mtime DESC LIMIT 10")]
    except sqlite3.OperationalError:
        pass
    finally:
        con.close()
    for r in recent:
        r["mtime_str"] = datetime.fromtimestamp(r.pop("mtime")).strftime("%m-%d %H:%M")

    edges: dict[str, int] = {}
    if RELATIONS_DB.exists():
        try:
            con = sqlite3.connect(f"file:{RELATIONS_DB}?mode=ro", uri=True)
            edges = {k: c for k, c in con.execute(
                "SELECT kind, COUNT(*) FROM edges GROUP BY kind")}
            con.close()
        except sqlite3.Error:
            pass

    weights = []
    if WEIGHTS_DB.exists():
        try:
            con = sqlite3.connect(f"file:{WEIGHTS_DB}?mode=ro", uri=True)
            weights = [{"rel_path": r[0], "computed": r[1]} for r in con.execute(
                "SELECT rel_path, computed FROM weights ORDER BY computed DESC LIMIT 8")]
            con.close()
        except sqlite3.Error:
            pass

    return {"domains": domains, "recent": recent, "edges": edges,
            "weights": weights, "pending": pending_count(),
            "superseded_total": edges.get("supersedes", 0)}


def pending_count() -> int:
    """待索引篇数（mtime 比对，只读不编码）。"""
    try:
        done = {}
        if DB_PATH.exists():
            con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
            done = {r[0]: r[1] for r in con.execute("SELECT rel_path, mtime FROM notes")}
            con.close()
        n = 0
        for rel, p in scopes.collect_files():
            if rel not in done or abs(done[rel] - p.stat().st_mtime) >= 1:
                n += 1
        return n
    except Exception:
        return -1


# ---------- 内容管理 ----------

def read_scope_text() -> str:
    return scopes.ensure_include_file().read_text(encoding="utf-8")


def validate_scope_text(text: str) -> list[str]:
    """语法校验：返回错误列表（空列表=通过）。"""
    errors = []
    for ln, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            body = line[1:]
            if " as " in body:
                body = body.split(" as ", 1)[0]
            p = Path(body.strip().strip('"'))
            if not p.is_absolute():
                errors.append(f"第{ln}行: @ 外部路径必须是绝对路径")
            elif not p.exists():
                errors.append(f"第{ln}行: 外部文件不存在 {p}")
        elif line.startswith("!"):
            if not line[1:].strip():
                errors.append(f"第{ln}行: 空的排除模式")
        elif not line:
            errors.append(f"第{ln}行: 空规则")
    return errors


def save_scope_text(text: str) -> list[str]:
    errors = validate_scope_text(text)
    if errors:
        return errors
    scopes.INCLUDE_PATH.write_text(text, encoding="utf-8")
    return []


def add_external_file(path: str, alias: str | None = None) -> tuple[bool, str]:
    p = Path(path).expanduser()
    if not p.is_absolute():
        return False, "必须提供绝对路径"
    if not p.exists() or not p.is_file():
        return False, f"文件不存在: {p}"
    name = alias or ("external/" + p.name)
    text = read_scope_text()
    if f"@{p}" in text or name in text:
        return False, "该文件已在范围内"
    line = f"@{p}" + (f" as {name}" if alias else "")
    sep = "" if text.endswith("\n") else "\n"
    scopes.INCLUDE_PATH.write_text(text + sep + line + "\n", encoding="utf-8")
    return True, name


SAFE_NOTE_RE = re.compile(r"^[\w\u4e00-\u9fff\-——（）()、，。 ]+(\/[\w\u4e00-\u9fff\-——（）()、，。 ]+)*\.md$")


def create_note(rel_path: str, content: str, overwrite: bool = False) -> tuple[bool, str]:
    """在 vault 内新建笔记（路径安全校验，绝不越出 vault）。"""
    rel = rel_path.strip().replace("\\", "/")
    if not rel.endswith(".md"):
        rel += ".md"
    if not SAFE_NOTE_RE.match(rel) or ".." in rel:
        return False, "路径含非法字符（只允许中英文/数字/空格/-_/等，且必须以 .md 结尾）"
    target = VAULT / rel
    if not str(target.resolve()).startswith(str(VAULT.resolve())):
        return False, "路径越出 vault"
    if target.exists() and not overwrite:
        return False, f"已存在: {rel}（勾选覆盖可重写）"
    target.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d")
    body = content if content.startswith("---") else \
        f"---\ncreated: {stamp}\n---\n\n# {Path(rel).stem}\n\n{content}"
    target.write_text(body, encoding="utf-8")
    return True, str(rel)
