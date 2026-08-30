/* vault-rag 控制台前端 — 原生 JS，无框架无 CDN（离线可用） */
"use strict";
const $ = (id) => document.getElementById(id);

/* ================= 跟随光效 ================= */
(() => {
  const glow = $("cursor-glow");
  let tx = innerWidth / 2, ty = innerHeight * .3, x = tx, y = ty;
  addEventListener("mousemove", (e) => { tx = e.clientX; ty = e.clientY; }, { passive: true });
  (function loop() {
    x += (tx - x) * 0.08; y += (ty - y) * 0.08;        // 缓动跟随
    glow.style.transform = `translate(${x}px, ${y}px)`;
    requestAnimationFrame(loop);
  })();
  // 玻璃卡片聚光边框：把鼠标位置写入卡片局部坐标
  addEventListener("mousemove", (e) => {
    for (const c of document.querySelectorAll(".glass")) {
      const r = c.getBoundingClientRect();
      if (e.clientX > r.left - 60 && e.clientX < r.right + 60 &&
          e.clientY > r.top - 60 && e.clientY < r.bottom + 60) {
        c.style.setProperty("--gx", (e.clientX - r.left) + "px");
        c.style.setProperty("--gy", (e.clientY - r.top) + "px");
      }
    }
  }, { passive: true });
})();

/* ================= 快捷设置面板（cc-switch 式供应商切换） ================= */
async function renderProviders() {
  const d = await api("/api/providers");
  const box = $("provider-list");
  box.innerHTML = "";
  d.presets.forEach((p) => {
    const active = p.url === d.active.url;
    const row = document.createElement("div");
    row.className = "provider" + (active ? " active" : "");
    row.innerHTML =
      `<div class="p-body"><div class="p-name">${escapeHtml(p.name)}</div>` +
      `<div class="p-sub">${escapeHtml(p.url)} · ${escapeHtml(p.model)}</div></div>` +
      (active ? `<span class="p-tag">● 使用中</span>` : `<span class="p-tag muted">切换</span>`);
    row.addEventListener("click", async () => {
      try {
        await post("/api/providers", { name: p.name });
        renderProviders();
        refreshStatus();
      } catch (e) { alert(e.message); }
    });
    box.appendChild(row);
  });
}

function openModal() {
  $("modal-backdrop").classList.add("open");
  renderProviders().catch(() => {});
  api("/api/status").then((st) => {
    $("modal-info").innerHTML =
      `<div class="row"><span class="muted">检索向量（本地端点）</span><span>${st.embed_ready
        ? `<span style="color:var(--ok)">✓ 在线 · 语义检索</span>`
        : `<span style="color:var(--warn)">✗ 离线 · 关键词检索</span>`}</span></div>` +
      `<div class="row"><span class="muted">检索端点</span><span style="font-size:11px">${escapeHtml(st.embed_url)}</span></div>`;
  }).catch(() => {});
  $("modal-key").focus();
}
function closeModal() { $("modal-backdrop").classList.remove("open"); }
$("btn-gear").addEventListener("click", openModal);
$("modal-close").addEventListener("click", closeModal);
$("modal-backdrop").addEventListener("click", (e) => {
  if (e.target === $("modal-backdrop")) closeModal();
});
addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });

$("btn-provider-test").addEventListener("click", async () => {
  const el = $("provider-test-msg");
  el.textContent = "测试中…";
  el.className = "msg muted";
  try {
    const r = await post("/api/chat/test");
    el.textContent = r.ok ? `✓ 连通（${r.latency_ms}ms）` : `✗ ${r.detail}`;
    el.className = "msg " + (r.ok ? "ok" : "err");
  } catch (e) { el.textContent = e.message; el.className = "msg err"; }
});

$("modal-key-save").addEventListener("click", async () => {
  const v = $("modal-key").value.trim();
  if (!v) { setMsgAuto("modal-key-msg", "输入为空，未保存", false); return; }
  try {
    const r = await post("/api/settings", { agnes_key: v });
    $("modal-key").value = "";
    setMsgAuto("modal-key-msg", r.key_set ? "✓ 已保存，现在可以直接提问了" : "保存失败", r.key_set, 6000);
    refreshStatus();
  } catch (e) { setMsg("modal-key-msg", e.message, false); }
});

/* ================= 通用 ================= */
async function api(path, opts) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let detail = r.statusText;
    try {
      const j = await r.json();
      detail = (j.detail && j.detail.errors && j.detail.errors.join("；")) ||
               (typeof j.detail === "string" ? j.detail : detail);
    } catch (_) {}
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
/* 极简 markdown：先转义再渲染，杜绝注入 */
function md(text) {
  const esc = text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const lines = esc.split("\n");
  let html = "", inList = false;
  const inline = (s) => s
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:[^)]+)\)/g, '<a href="$2" target="_blank" style="color:var(--cyan)">$1</a>');
  for (const ln of lines) {
    const li = ln.match(/^\s*[-*•]\s+(.*)/);
    const h = ln.match(/^#{1,4}\s+(.*)/);
    if (li) { if (!inList) { html += "<ul>"; inList = true; } html += `<li>${inline(li[1])}</li>`; continue; }
    if (inList) { html += "</ul>"; inList = false; }
    if (h) html += `<p><b style="color:var(--accent)">${inline(h[1])}</b></p>`;
    else if (ln.trim()) html += `<p>${inline(ln)}</p>`;
  }
  if (inList) html += "</ul>";
  return html;
}
const escapeHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/* ================= 标签页 ================= */
document.querySelectorAll("#tabs .tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll("#tabs .tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.add("active");
    if (btn.dataset.tab === "board") loadBoard();
    if (btn.dataset.tab === "manage") loadManage();
  });
});

/* ================= 状态条 ================= */
async function refreshStatus() {
  try {
    const st = await api("/api/status");
    const ok = st.consistent;
    const dotEmbed = $("dot-model"), dotChat = $("dot-chat");
    dotEmbed.className = "dot " + (st.embed_ready ? "ok" : "warn pulse");
    dotEmbed.title = st.embed_ready
      ? "语义检索端点在线（LM Studio）"
      : "语义检索端点离线 → 已用关键词检索；启动 LM Studio (1234) 恢复语义检索";
    dotChat.className = "dot " + (st.chat_ready ? "ok" : "err");
    dotChat.title = st.chat_ready ? "AI 问答已配置（云端生成）" : "AI 问答未配置 key（管理器 → 设置）";
    document.getElementById("status-text").textContent =
      `${st.notes} 篇 · ${st.chunks} 块 · ${st.db_mb}MB` + (ok ? "" : " · 库不一致!");
    $("status-pill").title =
      `上次索引: ${st.last_indexed}\n向量: ${st.vectors} · 缓存: ${st.embed_cache}\n` +
      `检索向量: ${st.embed_url} ${st.embed_ready ? "(在线)" : "(离线→关键词)"}\n` +
      `问答: ${st.chat_model} ${st.chat_ready ? "(已配置)" : "(未配置 key)"}\nvault: ${st.vault}`;
    $("send-sub").textContent = "";
  } catch (e) {
    $("dot-model").className = "dot err";
    document.getElementById("status-text").textContent = "后端离线";
  }
}

/* ================= 问答 ================= */
function addMsg(role, text) {
  const div = document.createElement("div");
  div.className = "msg " + role;
  div.innerHTML = `<div class="bubble"></div>`;
  if (text) div.querySelector(".bubble").innerHTML = md(text);
  $("chat-log").appendChild(div);
  $("chat-log").scrollTop = $("chat-log").scrollHeight;
  return div.querySelector(".bubble");
}

function renderSources(results) {
  $("sources-count").textContent = results.length ? `(${results.length})` : "";
  const box = $("sources-list");
  box.innerHTML = "";
  if (!results.length) {
    box.innerHTML = `<span class="empty">无来源</span>`;
    return;
  }
  results.forEach((s, i) => {
    const d = document.createElement("div");
    d.className = "source glass";
    d.title = "点击打开原文";
    d.innerHTML =
      `<span class="score">${s.score?.toFixed(3) ?? ""}</span>` +
      `<b>[${i + 1}]</b> <span class="path">${escapeHtml(s.rel_path)}</span>` +
      (s.section ? `<span class="sec">${escapeHtml(s.section).slice(0, 120)}</span>` : "") +
      (s.superseded ? `<span class="warn">⚠ 已被更新版本取代</span>` : "");
    d.addEventListener("click", () => {
      post("/api/open", { rel_path: s.rel_path }).catch((e) => alert("打开失败: " + e.message));
    });
    box.appendChild(d);
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
  const bubble = addMsg("assistant");
  bubble.innerHTML = `<p class="muted">${searchOnly ? "检索中" : "检索并思考中"}<span class="stream-caret"></span></p>`;
  const caret = `<span class="stream-caret"></span>`;
  let acc = "";

  try {
    if (searchOnly) {
      const out = await post("/api/search", { q, k: 8 });
      renderSources(out.results);
      bubble.innerHTML = out.results.length
        ? md(`检索到 **${out.results.length}** 条相关内容（右侧来源，点击可打开原文）。`)
        : md("没有检索到相关内容。");
      if (out.mode.startsWith("keyword"))
        bubble.innerHTML += `<span class="fallback-note">⚠ ${escapeHtml(out.mode)}</span>`;
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
          let ev;
          try { ev = JSON.parse(line.slice(5)); } catch (_) { continue; }
          if (ev.type === "sources") {
            renderSources(ev.results);
          } else if (ev.type === "delta") {
            acc += ev.text;
            bubble.innerHTML = md(acc) + caret;
            $("chat-log").scrollTop = $("chat-log").scrollHeight;
          } else if (ev.type === "warning") {
            acc += `\n\n⚠ ${ev.message}`;
            bubble.innerHTML = md(acc);
          } else if (ev.type === "fallback") {
            renderSources(ev.results);
            bubble.innerHTML =
              `<span class="fallback-note">⚠ AI 生成不可用：${escapeHtml(ev.message)}<br>` +
              `→ <button class="linklike" data-open-settings>打开设置面板粘贴 Key</button>` +
              `（检索不受影响，当前展示本地检索结果）</span>` +
              md("以下为本地检索结果（右侧可打开原文）：");
          } else if (ev.type === "error") {
            bubble.innerHTML = md(acc || "") + `<span class="fallback-note">✗ 出错: ${escapeHtml(ev.message)}</span>`;
          }
        }
      }
      if (!acc && bubble.textContent.includes("检索并思考中"))
        bubble.innerHTML = `<span class="fallback-note">(无返回)</span>`;
    }
  } catch (e) {
    bubble.innerHTML = `<span class="fallback-note">✗ 请求失败: ${escapeHtml(e.message)}</span>`;
  } finally {
    setBusy(false);
    $("chat-log").scrollTop = $("chat-log").scrollHeight;
  }
}
$("btn-send").addEventListener("click", () => sendChat(false));
$("btn-search-only").addEventListener("click", () => sendChat(true));
$("chat-log").addEventListener("click", (e) => {
  if (e.target.closest("[data-open-settings]")) openModal();
});
$("chat-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(false); }
});
document.querySelectorAll(".chip").forEach((c) =>
  c.addEventListener("click", () => { $("chat-input").value = c.textContent; sendChat(false); }));

/* ================= 看板 ================= */
function countUp(el, target) {
  const t0 = performance.now(), dur = 850;
  (function step(t) {
    const p = Math.min(1, (t - t0) / dur);
    el.textContent = Math.round(target * (1 - Math.pow(1 - p, 3))).toLocaleString();
    if (p < 1) requestAnimationFrame(step);
  })(t0);
}
async function loadBoard() {
  try {
    const [st, d] = await Promise.all([api("/api/status"), api("/api/dashboard")]);
    const cards = [
      ["笔记", st.notes, ""], ["文本块", st.chunks, ""],
      ["向量", st.vectors, st.consistent ? "" : "与文本块不一致!"],
      ["待索引", d.pending < 0 ? 0 : d.pending, d.pending > 0 ? "有新内容" : ""],
      ["embed 缓存", st.embed_cache, ""],
      ["被取代文档", d.superseded_total, ""],
    ];
    $("cards").innerHTML = cards.map(([lbl, num, err], i) =>
      `<div class="card glass ${err ? "bad" : ""}" style="animation:fadeup .4s ${i * 0.05}s both">` +
      `<div class="num">0</div><div class="lbl">${lbl}${err ? " · " + err : ""}</div></div>`).join("");
    document.querySelectorAll("#cards .num").forEach((el, i) => countUp(el, cards[i][1]));

    const maxN = Math.max(1, ...d.domains.map((x) => x.notes));
    $("domains").innerHTML = d.domains.map((x) =>
      `<div class="bar-row"><div class="bar-lbl"><b title="${escapeHtml(x.domain)}">${escapeHtml(x.domain)}</b>` +
      `<span class="muted">${x.notes} 篇 / ${x.chunks} 块</span></div>` +
      `<div class="bar"><div data-w="${(x.notes / maxN * 100).toFixed(1)}"></div></div></div>`
    ).join("") || `<span class="empty">索引为空</span>`;
    requestAnimationFrame(() =>
      document.querySelectorAll("#domains .bar > div").forEach(
        (b) => b.style.width = b.dataset.w + "%"));

    const edgeNames = { supersedes: "版本取代", sibling_next: "时序链", complements: "跨簇互补", references: "wikilink" };
    $("edges-hint").textContent = st.relations_built ? "" : "（relations.db 未构建）";
    const edgeKeys = Object.keys(d.edges);
    $("edges").innerHTML = edgeKeys.length
      ? edgeKeys.map((k) => `<div class="row"><span>${edgeNames[k] || k}</span><span>${d.edges[k]}</span></div>`).join("")
      : `<span class="empty">暂无关系边</span>`;

    $("weights-hint").textContent = st.weights_built ? "" : "（weights.db 未构建）";
    $("weights").innerHTML = d.weights.length
      ? d.weights.map((w) => `<div class="row"><span title="${escapeHtml(w.rel_path)}">${escapeHtml(w.rel_path)}</span><span>${w.computed}</span></div>`).join("")
      : `<span class="empty">暂无权重数据</span>`;

    $("recent").innerHTML = d.recent.length
      ? d.recent.map((r) => `<div class="row"><a data-path="${escapeHtml(r.rel_path)}" title="${escapeHtml(r.rel_path)}">${escapeHtml(r.rel_path)}</a>` +
          `<span class="time muted">${r.mtime_str}</span></div>`).join("")
      : `<span class="empty">暂无</span>`;
    $("recent").querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () =>
        post("/api/open", { rel_path: a.dataset.path }).catch((e) => alert(e.message))));
  } catch (e) {
    $("cards").innerHTML = `<div class="card glass bad"><div class="num">✗</div><div class="lbl">${escapeHtml(e.message)}</div></div>`;
  }
}

/* ================= 管理器 ================= */
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
      `<div class="row"><span class="muted">模型</span><span>${escapeHtml(cfg.model)}</span></div>` +
      `<div class="row"><span class="muted">端点</span><span style="font-size:11px;word-break:break-all">${escapeHtml(cfg.endpoint)}</span></div>`;
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
          (st.finished ? ` · 上次${st.ok === false ? " ✗失败" : " ✓完成"}` : "");
        if (st.log) {
          $("index-log").className = "log";
          $("index-log").textContent = st.log;
          $("index-log").scrollTop = $("index-log").scrollHeight;
        }
      }
    } catch (_) {}
  };
  tick();
  pollTimer = setInterval(tick, 2000);
}

$("btn-index").addEventListener("click", async () => {
  try {
    const r = await post("/api/index/refresh", {});
    setMsgAuto("index-state", r.message, r.ok);
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

/* ================= 启动 ================= */
refreshStatus();
setInterval(refreshStatus, 10000);
loadManage();
