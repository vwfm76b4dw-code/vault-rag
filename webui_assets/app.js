/* vault-rag 控制台前端逻辑（无框架，原生 fetch + SSE） */
"use strict";
const $ = (id) => document.getElementById(id);

/* ---------- 通用 ---------- */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try { detail = (await r.json()).detail?.errors?.join("；") || (await r.json())?.detail || detail; }
    catch (_) { /* keep statusText */ }
    throw new Error(detail);
  }
  return r.json();
}
const post = (path, body) => api(path, {
  method: "POST", headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});
function setMsg(id, text, ok) {
  const el = $(id);
  el.textContent = text;
  el.className = "msg " + (ok ? "ok" : "err");
}
function setMsgAuto(id, text, ok, ms = 4000) {
  setMsg(id, text, ok);
  if (text) setTimeout(() => { if ($(id).textContent === text) $(id).textContent = ""; }, ms);
}

/* ---------- 标签页 ---------- */
document.querySelectorAll("nav .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("nav .tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "board") loadBoard();
    if (btn.dataset.tab === "manage") loadManage();
  });
});

/* ---------- 状态条 ---------- */
async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const dot = document.querySelector("#status-pill .dot");
    const ok = st.consistent;
    dot.className = "dot " + (ok ? "ok" : "err");
    $("status-text").textContent =
      `${st.notes} 篇 · ${st.chunks} 块 · ${st.db_mb}MB` + (ok ? "" : " · 库不一致!");
    $("status-pill").title =
      `上次索引: ${st.last_indexed}\n向量: ${st.vectors}\n缓存: ${st.embed_cache}\n` +
      `问答模型: ${st.chat_model} (${st.chat_ready ? "key已配置" : "未配置key"})\nvault: ${st.vault}`;
  } catch (e) {
    document.querySelector("#status-pill .dot").className = "dot err";
    $("status-text").textContent = "后端离线";
  }
}

/* ---------- 问答 ---------- */
function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `<div class="bubble"></div>`;
  div.querySelector(".bubble").textContent = text;
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return div.querySelector(".bubble");
}

function renderSources(results) {
  $("sources-count").textContent = results.length ? `(${results.length})` : "";
  $("sources-list").innerHTML = "";
  if (!results.length) {
    $("sources-list").innerHTML = `<span class="muted">无来源</span>`;
    return;
  }
  results.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "source";
    d.title = "点击打开原文";
    d.innerHTML =
      `<span class="score">${s.score?.toFixed(3) ?? ""}</span>` +
      `<b>[${i + 1}]</b> <span class="path">${s.rel_path}</span>` +
      (s.section ? `<span class="sec">${s.section}</span>` : "") +
      (s.superseded ? `<span class="warn">⚠ 已被更新版本取代</span>` : "");
    d.addEventListener("click", () => {
      post("/api/open", { rel_path: s.rel_path }).catch((e) => alert("打开失败: " + e.message));
    });
    $("sources-list").appendChild(d);
  });
}

function setBusy(busy) {
  $("btn-send").disabled = busy;
  $("btn-search-only").disabled = busy;
}

async function sendChat(searchOnly) {
  const q = $("chat-input").value.trim();
  if (!q) return;
  $("chat-input").value = "";
  addMsg("user", q);
  setBusy(true);
  const bubble = addMsg("assistant", searchOnly ? "检索中…" : "思考中…");
  const cursor = document.createElement("span");
  cursor.className = "stream-cursor";
  let acc = "";

  try {
    if (searchOnly) {
      const out = await post("/api/search", { q, k: 8 });
      renderSources(out.results);
      bubble.textContent = out.results.length
        ? `检索到 ${out.results.length} 条相关内容（见右侧来源，点击可打开原文）。`
        : "没有检索到相关内容。";
      if (out.mode.startsWith("keyword")) bubble.textContent += "\n⚠ " + out.mode;
    } else {
      const r = await fetch("/api/chat", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ q, k: 6 }),
      });
      if (!r.ok || !r.body) throw new Error("HTTP " + r.status);
      const reader = r.body.getReader();
      const dec = new TextDecoder();
      let buf = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (!line.startsWith("data:")) continue;
          const ev = JSON.parse(line.slice(5));
          if (ev.type === "sources") {
            renderSources(ev.results);
          } else if (ev.type === "delta") {
            acc += ev.text;
            bubble.innerHTML = "";
            bubble.textContent = acc;
            bubble.appendChild(cursor);
            $("chat-log").scrollTop = $("chat-log").scrollHeight;
          } else if (ev.type === "warning") {
            acc += `\n\n⚠ ${ev.message}`;
            bubble.textContent = acc;
          } else if (ev.type === "fallback") {
            renderSources(ev.results);
            bubble.textContent = `⚠ AI 生成不可用：${ev.message}\n\n以下为本地检索结果（右侧可打开原文）：`;
          } else if (ev.type === "error") {
            bubble.textContent = (acc || "") + `\n\n✗ 出错: ${ev.message}`;
          }
        }
      }
      if (!acc && bubble.textContent === "思考中…") bubble.textContent = "(无返回)";
    }
  } catch (e) {
    bubble.textContent = `✗ 请求失败: ${e.message}`;
  } finally {
    cursor.remove();
    setBusy(false);
    $("chat-log").scrollTop = $("chat-log").scrollHeight;
  }
}
$("btn-send").addEventListener("click", () => sendChat(false));
$("btn-search-only").addEventListener("click", () => sendChat(true));
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(false); }
});

/* ---------- 看板 ---------- */
async function loadBoard() {
  try {
    const [st, d] = await Promise.all([api("/api/status"), api("/api/dashboard")]);
    const cards = [
      ["笔记", st.notes, ""], ["文本块", st.chunks, ""],
      ["向量", st.vectors, st.consistent ? "" : "与文本块不一致!"],
      ["待索引", d.pending < 0 ? "?" : d.pending, d.pending > 0 ? "有新内容" : ""],
      ["embed 缓存", st.embed_cache, ""],
      ["被取代文档", d.superseded_total, ""],
    ];
    $("cards").innerHTML = cards.map(([lbl, num, err]) =>
      `<div class="card ${err ? "bad" : ""}"><div class="num">${num}</div>` +
      `<div class="lbl">${lbl}${err ? " · " + err : ""}</div></div>`).join("");

    const maxN = Math.max(1, ...d.domains.map((x) => x.notes));
    $("domains").innerHTML = d.domains.map((x) =>
      `<div class="bar-row"><div class="bar-lbl"><b title="${x.domain}">${x.domain}</b>` +
      `<span class="muted">${x.notes} 篇 / ${x.chunks} 块</span></div>` +
      `<div class="bar"><div style="width:${(x.notes / maxN * 100).toFixed(1)}%"></div></div></div>`
    ).join("") || `<span class="muted">索引为空</span>`;

    const edgeNames = { supersedes: "版本取代", sibling_next: "时序链", complements: "跨簇互补", references: "wikilink" };
    const edgeKeys = Object.keys(d.edges);
    $("edges-hint").textContent = st.relations_built ? "" : "（relations.db 未构建，跑 relations.py build）";
    $("edges").innerHTML = edgeKeys.length
      ? edgeKeys.map((k) => `<div class="row"><span>${edgeNames[k] || k}</span><span>${d.edges[k]}</span></div>`).join("")
      : `<span class="muted">暂无关系边</span>`;

    $("weights-hint").textContent = st.weights_built ? "" : "（weights.db 未构建，跑 weight_v2.py）";
    $("weights").innerHTML = d.weights.length
      ? d.weights.map((w) => `<div class="row"><span title="${w.rel_path}">${w.rel_path}</span><span>${w.computed}</span></div>`).join("")
      : `<span class="muted">暂无权重数据</span>`;

    $("recent").innerHTML = d.recent.length
      ? d.recent.map((r) => `<div class="row"><a data-path="${r.rel_path}" title="${r.rel_path}">${r.rel_path}</a>` +
          `<span class="time">${r.mtime_str}</span></div>`).join("")
      : `<span class="muted">暂无</span>`;
    $("recent").querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () =>
        post("/api/open", { rel_path: a.dataset.path }).catch((e) => alert(e.message))));
  } catch (e) {
    $("cards").innerHTML = `<div class="card bad"><div class="num">✗</div><div class="lbl">${e.message}</div></div>`;
  }
}

/* ---------- 管理器 ---------- */
async function loadManage() {
  try {
    const s = await api("/api/scope");
    if ($("scope-text").dataset.loaded !== "1") {
      $("scope-text").value = s.text;
      $("scope-text").dataset.loaded = "1";
    }
    const cfg = await api("/api/settings");
    $("endpoint-info").innerHTML =
      `<div class="row"><span class="muted">Key</span><span>${cfg.key_set ? "✓ 已配置" : "✗ 未配置"}</span></div>` +
      `<div class="row"><span class="muted">模型</span><span>${cfg.model}</span></div>` +
      `<div class="row"><span class="muted">端点</span><span style="font-size:11px">${cfg.endpoint}</span></div>`;
    pollIndex();
  } catch (e) { setMsg("scope-msg", e.message, false); }
}

$("btn-scope-save").addEventListener("click", async () => {
  try {
    await post("/api/scope", { text: $("scope-text").value });
    setMsgAuto("scope-msg", "✓ 已保存（下次增量索引生效）", true);
  } catch (e) { setMsg("scope-msg", e.message, false); }
});

$("btn-browse").addEventListener("click", async () => {
  try {
    const r = await api("/api/pick-file");
    if (r.path) $("ext-path").value = r.path;
  } catch (e) { setMsgAuto("ext-msg", "桌面窗口模式才有文件对话框，请直接粘贴路径", false); }
});

$("btn-ext-add").addEventListener("click", async () => {
  try {
    const r = await post("/api/scope/add-external", {
      path: $("ext-path").value.trim(), alias: $("ext-alias").value.trim(),
    });
    if (r.ok) {
      setMsgAuto("ext-msg", "✓ 已加入: " + r.message, true);
      $("ext-path").value = ""; $("ext-alias").value = "";
      const s = await api("/api/scope");
      $("scope-text").value = s.text;
    } else setMsgAuto("ext-msg", r.message, false);
  } catch (e) { setMsg("ext-msg", e.message, false); }
});

$("btn-note-create").addEventListener("click", async () => {
  try {
    const r = await post("/api/note", {
      rel_path: $("note-path").value.trim(),
      content: $("note-content").value,
      overwrite: $("note-overwrite").checked,
    });
    if (r.ok) {
      setMsgAuto("note-msg", "✓ 已创建 " + r.message + "，正在启动增量索引…", true, 8000);
      $("note-path").value = ""; $("note-content").value = "";
      await post("/api/index/refresh");
      pollIndex();
    } else setMsgAuto("note-msg", r.message, false);
  } catch (e) { setMsg("note-msg", e.message, false); }
});

let pollTimer = null;
function pollIndex() {
  if (pollTimer) return;
  const tick = async () => {
    try {
      const st = await api("/api/index/status");
      const state = $("index-state");
      if (st.running) {
        state.textContent = `运行中 ${st.elapsed}s · 待索引 ${st.pending < 0 ? "?" : st.pending} 篇`;
        $("index-log").className = "log busy";
        $("index-log").textContent = st.log || "（编码中…）";
        $("index-log").scrollTop = $("index-log").scrollHeight;
      } else {
        state.textContent = `待索引 ${st.pending < 0 ? "?" : st.pending} 篇` +
          (st.finished ? ` · 上次 ${st.ok === false ? "✗失败" : "✓完成"} ${st.log ? "" : ""}` : "");
        if (st.log) {
          $("index-log").className = "log";
          $("index-log").textContent = st.log;
          $("index-log").scrollTop = $("index-log").scrollHeight;
        }
      }
    } catch (_) { /* 忽略轮询错误 */ }
  };
  tick();
  pollTimer = setInterval(tick, 2000);
}

$("btn-index").addEventListener("click", async () => {
  try {
    const r = await post("/api/index/refresh", {});
    setMsgAuto("index-state", r.ok ? r.message : r.message, r.ok);
    pollIndex();
  } catch (e) { alert(e.message); }
});

$("btn-key-save").addEventListener("click", async () => {
  const v = $("key-input").value.trim();
  if (!v) { setMsgAuto("key-msg", "输入为空，未保存", false); return; }
  try {
    const r = await post("/api/settings", { agnes_key: v });
    $("key-input").value = "";
    setMsgAuto("key-msg", r.key_set ? "✓ Key 已保存" : "保存失败", r.key_set);
    refreshStatus();
  } catch (e) { setMsg("key-msg", e.message, false); }
});

/* ---------- 启动 ---------- */
refreshStatus();
setInterval(refreshStatus, 15000);
loadManage();      // 默认页是问答，但管理器状态先拉一次
