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

from vault_rag.config import (CHAT_API_KEY_ENVS, CHAT_API_URL, CHAT_MODEL, CHAT_TIMEOUT,
                    DB_PATH, DATA_DIR, FTS_DB, LOCAL_SETTINGS_PATH, RELATIONS_DB,
                    VAULT, WEIGHTS_DB)
from vault_rag import scope as scopes

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


# ---------- 供应商档案（cc-switch 式：预设 + 自定义增删改）----------
# 兼容性：全部走 OpenAI 兼容 /chat/completions；每个档案可带独立 key
# （留空回落全局 key），本地推理类（Ollama/llama.cpp）无需 key。

PROVIDER_PRESETS = [
    {"name": "Agnes 国内", "url": "https://api.agnes-ai.cn/v1/chat/completions",
     "model": "agnes-2.5-flash"},
    {"name": "DeepSeek", "url": "https://api.deepseek.com/v1/chat/completions",
     "model": "deepseek-chat"},
    {"name": "智谱 GLM", "url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
     "model": "glm-4-flash"},
    {"name": "Kimi 月之暗面", "url": "https://api.moonshot.cn/v1/chat/completions",
     "model": "moonshot-v1-8k"},
    {"name": "通义千问", "url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
     "model": "qwen-plus"},
    {"name": "硅基流动", "url": "https://api.siliconflow.cn/v1/chat/completions",
     "model": "Qwen/Qwen2.5-7B-Instruct"},
    {"name": "OpenRouter", "url": "https://openrouter.ai/api/v1/chat/completions",
     "model": "openrouter/auto"},
    {"name": "OpenAI", "url": "https://api.openai.com/v1/chat/completions",
     "model": "gpt-4o-mini"},
    {"name": "Ollama 本地", "url": "http://127.0.0.1:11434/v1/chat/completions",
     "model": "llama3.1"},
    {"name": "llama.cpp 本地", "url": "http://127.0.0.1:8080/v1/chat/completions",
     "model": "qwen3"},
]


def _is_local_url(url: str) -> bool:
    return any(h in url for h in ("127.0.0.1", "localhost", "0.0.0.0"))


def chat_profiles() -> list[dict]:
    """预设 + 自定义档案；同名自定义**覆盖**预设（否则用户给预设存的 key
    被排在前面的无 key 预设遮蔽——UI 显示没存上，实际却在生效）。"""
    custom = {c["name"]: dict(c)
              for c in (load_local_settings().get("chat_profiles") or [])}
    out = []
    for p in PROVIDER_PRESETS:
        out.append(custom.pop(p["name"], None) or dict(p))
    out.extend(custom.values())
    return out


def _provider_key(prof: dict) -> str:
    """key 解析：档案自带 key > 全局 agnes_key > 环境变量。"""
    k = str(prof.get("key") or "")
    return k or chat_api_key()


def active_provider() -> dict:
    """当前生效的生成供应商（存 _local_settings.json，改完即时生效）。"""
    s = load_local_settings()
    cur = s.get("provider")
    profiles = chat_profiles()
    if isinstance(cur, dict) and cur.get("url"):
        prof = {"name": str(cur.get("name", "自定义")),
                "url": str(cur["url"]), "model": str(cur.get("model", ""))}
        for p in profiles:                    # 带回档案里存的独立 key
            if p["name"] == prof["name"] and p.get("key"):
                prof["key"] = p["key"]
        return prof
    for p in profiles:
        if p["name"] == cur:
            return dict(p)
    return dict(profiles[0])                  # 默认 Agnes 国内


def chat_ready() -> bool:
    prof = active_provider()
    if _is_local_url(prof["url"]):
        return True                           # 本地推理无需 key
    return bool(_provider_key(prof))


def switch_provider(name: str | None = None, url: str | None = None,
                    model: str | None = None, key: str | None = None) -> dict:
    """按名切换；带 url 则新增/覆盖自定义档案。返回生效档案。"""
    if url:
        prof = {"name": name or "自定义", "url": url, "model": model or "", "custom": True}
        if key:
            prof["key"] = key
        s = load_local_settings()
        profiles = [p for p in (s.get("chat_profiles") or []) if p.get("name") != prof["name"]]
        profiles.append(prof)
        save_local_settings({"chat_profiles": profiles})
        save_local_settings({"provider": {"name": prof["name"], "url": prof["url"],
                                          "model": prof["model"]}})
        return prof
    if not name:
        raise ValueError("需要 name 或 url")
    prof = next((p for p in chat_profiles() if p["name"] == name), None)
    if prof is None:
        raise ValueError(f"未知供应商: {name}")
    if key is not None:                       # 给预设档案也存独立 key
        s = load_local_settings()
        profiles = [p for p in (s.get("chat_profiles") or []) if p.get("name") != name]
        profiles.append({"name": name, "url": prof["url"], "model": prof["model"],
                         "key": key, "custom": True})
        save_local_settings({"chat_profiles": profiles})
        prof = next(p for p in chat_profiles() if p["name"] == name)
    save_local_settings({"provider": {"name": prof["name"], "url": prof["url"],
                                      "model": prof["model"]}})
    return prof


def delete_provider(name: str) -> dict:
    """仅自定义档案可删；删当前生效的则回落默认。"""
    s = load_local_settings()
    profiles = [p for p in (s.get("chat_profiles") or []) if p.get("name") != name]
    if len(profiles) == len(s.get("chat_profiles") or []):
        raise ValueError(f"预设档案不可删除: {name}")
    save_local_settings({"chat_profiles": profiles})
    if (s.get("provider") or {}).get("name") == name:
        save_local_settings({"provider": dict(PROVIDER_PRESETS[0])})
    return {"deleted": name}


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


# ---------- OpenAI 兼容端点调用（多供应商） ----------

class ChatUnavailable(Exception):
    pass


def get_pref(key: str, default):
    """用户偏好（temperature/top_k 等），存 _local_settings.json 的 prefs。"""
    return (load_local_settings().get("prefs") or {}).get(key, default)


def stream_chat(messages: list[dict], temperature: float | None = None):
    """流式生成，逐段 yield 文本增量。失败抛 ChatUnavailable。走当前生效供应商。

    兼容性：SSE 无 charset 强制 UTF-8；流式不支持时自动退非流式；
    SSE 内嵌 error 事件转 ChatUnavailable。
    """
    prof = active_provider()
    key = _provider_key(prof)
    local = _is_local_url(prof["url"])
    if not key and not local:
        raise ChatUnavailable(f"供应商「{prof['name']}」未配置 key（设置面板可填）")
    if temperature is None:
        temperature = float(get_pref("temperature", 0.3))
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    body = {"model": prof["model"], "messages": messages,
            "temperature": temperature, "stream": True}
    try:
        r = requests.post(prof["url"], headers=headers, json=body,
                          stream=True, timeout=(15, CHAT_TIMEOUT))
        if r.status_code != 200:
            hint = r.text[:150]
            # 部分供应商不支持 stream → 退非流式一次性吐出
            if r.status_code in (400, 404, 422) and ("stream" in hint.lower()):
                text = chat_once(messages, temperature)
                if text:
                    yield text
                return
            raise ChatUnavailable(f"端点 HTTP {r.status_code}: {hint}")
        # SSE 不带 charset 时 requests 默认按 ISO-8859-1 解码，中文必乱码 → 强制 UTF-8
        r.encoding = "utf-8"
        got = False
        for line in r.iter_lines(decode_unicode=True):
            if not line or not line.startswith("data:"):
                continue
            payload = line[5:].strip()
            if payload == "[DONE]":
                break
            try:
                obj = json.loads(payload)
            except Exception:
                continue
            if isinstance(obj, dict) and obj.get("error"):
                raise ChatUnavailable(f"端点返回错误: {str(obj['error'])[:120]}")
            try:
                delta = obj["choices"][0]["delta"].get("content")
            except Exception:
                continue
            if delta:
                got = True
                yield delta
        if not got and not local:
            yield ""                              # 空回复也让前端收尾
    except ChatUnavailable:
        raise
    except requests.RequestException as e:
        raise ChatUnavailable(f"端点连接失败: {e}") from e


def chat_once(messages: list[dict], temperature: float | None = None) -> str:
    """非流式兜底。"""
    prof = active_provider()
    key = _provider_key(prof)
    local = _is_local_url(prof["url"])
    if not key and not local:
        raise ChatUnavailable("未配置 API key")
    if temperature is None:
        temperature = float(get_pref("temperature", 0.3))
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.post(
        prof["url"], headers=headers,
        json={"model": prof["model"], "messages": messages, "temperature": temperature},
        timeout=(15, CHAT_TIMEOUT))
    if r.status_code != 200:
        raise ChatUnavailable(f"端点 HTTP {r.status_code}: {r.text[:120]}")
    return r.json()["choices"][0]["message"]["content"]


def vision_chat(prompt: str, image_bytes: bytes,
                temperature: float = 0.2) -> str:
    """视觉问答（错题识别用）：OpenAI 多模态 parts 格式，走当前供应商。

    供应商不支持图像输入时会得到非 200 / 内容异常 → 一律 ChatUnavailable，
    由调用方转成用户可读的提示（绝不静默）。
    """
    import base64 as _b64
    prof = active_provider()
    key = _provider_key(prof)
    local = _is_local_url(prof["url"])
    if not key and not local:
        raise ChatUnavailable("未配置 API key（设置面板可填）")
    b64 = _b64.b64encode(image_bytes).decode()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    r = requests.post(
        prof["url"], headers=headers,
        json={"model": prof["model"], "temperature": temperature,
              "messages": [{"role": "user", "content": [
                  {"type": "text", "text": prompt},
                  {"type": "image_url",
                   "image_url": {"url": f"data:image/png;base64,{b64}"}}]}]},
        timeout=(15, 120))
    if r.status_code != 200:
        hint = r.text[:150]
        raise ChatUnavailable(f"供应商不支持图像输入或请求失败（HTTP {r.status_code}）：{hint}")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (KeyError, ValueError) as e:
        raise ChatUnavailable(f"视觉响应结构异常：{e}") from e


def test_provider(timeout: float = 15.0) -> dict:
    """连通性测试：不发流，问一声"ping"。返回 {ok, latency_ms, detail}。"""
    t0 = time.time()
    try:
        reply = chat_once([{"role": "user", "content": "ping，请只回复:pong"}], temperature=0)
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "detail": f"连通 · 回复: {reply[:30]}"}
    except ChatUnavailable as e:
        return {"ok": False, "latency_ms": int((time.time() - t0) * 1000), "detail": str(e)}


# ---------- 检索 ----------

def retrieve(query: str, top_k: int = 6) -> list[dict]:
    """语义检索 + 被取代标记。embedding 模型不可用时抛异常由调用方处理。"""
    from vault_rag.search import search as _search
    hits = _search(query, top_k=top_k)
    superseded = superseded_paths()
    for h in hits:
        h["superseded"] = h["rel_path"] in superseded
    return hits


def keyword_terms(query: str) -> list[str]:
    """检索词切分：英文整词；中文长串切 2-gram（整句精确匹配基本命不中）。"""
    toks = []
    for run in re.findall(r"[一-鿿]{2,}|[A-Za-z0-9]{2,}", query):
        if run[0].isascii():
            toks.append(run.lower())
        elif len(run) <= 2:
            toks.append(run)
        else:
            toks += [run[i:i + 2] for i in range(len(run) - 1)]
    return toks or ([query.strip()] if query.strip() else [])


def keyword_fallback(query: str, top_k: int = 6) -> list[dict]:
    """embedding 不可用时的关键词兜底（分词 LIKE 命中占比排序）。"""
    terms = keyword_terms(query)
    if not terms:
        return []
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    try:
        # 命中任一切分词即入候选（OR），占比决定排序；限 200 行防全表扫
        where = " OR ".join("text LIKE ?" for _ in terms[:16])
        rows = con.execute(
            f"SELECT rel_path, section, text FROM chunks WHERE {where} LIMIT 400",
            [f"%{t}%" for t in terms[:16]]).fetchall()
        scored = []
        for r in rows:
            t = r["text"]
            sc = sum(1 for x in terms if x in t) / len(terms)
            if sc <= 0:
                continue
            scored.append({"rel_path": r["rel_path"], "section": r["section"] or "",
                           "text": t, "score": sc, "superseded": False})
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
    scopes.include_path().write_text(text, encoding="utf-8")
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
    scopes.include_path().write_text(text + sep + line + "\n", encoding="utf-8")
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
