/* vault-rag 控制台前端 — 原生 JS，无框架无 CDN（离线可用） */
"use strict";
const $ = (id) => document.getElementById(id);

/* ================= 跟随光效 ================= */
(() => {
  const glow = $("cursor-glow");
  let tx = innerWidth / 2, ty = innerHeight * .3, x = tx, y = ty;
  addEventListener("mousemove", (e) => { tx = e.clientX; ty = e.clientY; }, { passive: true });
  (function loop() {
    x += (tx - x) * 0.12; y += (ty - y) * 0.12;        // 缓动跟随（快而不僵）
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

/* ================= 模型管理面板（cc-switch 式：生成 / 检索两页签） ================= */
document.querySelectorAll(".mtab").forEach((t) => t.addEventListener("click", () => {
  document.querySelectorAll(".mtab").forEach((x) => x.classList.remove("active"));
  document.querySelectorAll(".mtab-panel").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  $("mtab-" + t.dataset.mtab).classList.add("active");
}));

/* ---- 生成供应商：档案列表（预设+自定义，点击切换，可增删改） ---- */
async function renderProviders() {
  const d = await api("/api/providers");
  const box = $("provider-list");
  box.innerHTML = "";
  d.profiles.forEach((p) => {
    const active = p.name === d.active.name;
    const row = document.createElement("div");
    row.className = "provider" + (active ? " active" : "");
    row.innerHTML =
      `<div class="p-body"><div class="p-name">${escapeHtml(p.name)}</div>` +
      `<div class="p-sub">${escapeHtml(p.url)} · ${escapeHtml(p.model)}</div></div>` +
      (p.key ? `<span class="p-tag muted" title="档案自带 key">🔑</span>` : ``) +
      `<span class="p-tag linklike" data-p-key title="设置/更改该档案专用 key">Key</span>` +
      (active ? `<span class="p-tag">● 使用中</span>`
              : `<span class="p-tag muted">切换</span>`) +
      (p.custom ? `<button class="p-del" title="删除该档案">✕</button>` : ``);
    row.querySelector("[data-p-key]").addEventListener("click", async (e) => {
      e.stopPropagation();
      const k = prompt(`为「${p.name}」设置专用 Key（当前${p.key ? "已配置" : "未配置"}；留空取消）：`);
      if (!k) return;
      try {
        await post("/api/providers", { name: p.name, key: k });
        setMsgAuto("np-msg", `✓ Key 已保存并生效（${p.name}）`, true);
        renderProviders(); refreshStatus();
      } catch (err) { alert(err.message); }
    });
    row.addEventListener("click", async (e) => {
      if (e.target.classList.contains("p-del")) return;
      try { await post("/api/providers", { name: p.name }); renderProviders(); refreshStatus(); }
      catch (err) { alert(err.message); }
    });
    const del = row.querySelector(".p-del");
    if (del) del.addEventListener("click", async (e) => {
      e.stopPropagation();
      if (!confirm(`删除档案「${p.name}」？`)) return;
      try {
        await api("/api/providers", { method: "DELETE",
          headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: p.name }) });
        renderProviders(); refreshStatus();
      } catch (err) { alert(err.message); }
    });
    box.appendChild(row);
  });
}

/* ---- 检索 Embedding 页签 ---- */
let embedCfg = null;
async function renderEmbed() {
  embedCfg = await api("/api/embed/config");
  document.querySelectorAll(`#embed-mode-row input`).forEach((r) => {
    r.checked = r.value === embedCfg.backend;
    r.onchange = async () => {
      await post("/api/embed/config", { backend: r.value });
      renderEmbed();
    };
  });
  // HTTP 端点档案
  const box = $("embed-profile-list");
  box.innerHTML = "";
  (embedCfg.http_profiles || []).forEach((p) => {
    const active = p.name === embedCfg.http_active;
    const row = document.createElement("div");
    row.className = "provider" + (active ? " active" : "");
    row.innerHTML =
      `<div class="p-body"><div class="p-name">${escapeHtml(p.name)}${active ? ' <span class="p-tag">●</span>' : ""}</div>` +
      `<div class="p-sub">${escapeHtml(p.url)} · ${escapeHtml(p.model)}</div></div>`;
    row.addEventListener("click", async () => {
      await post("/api/embed/config", { http_active: p.name });
      renderEmbed();
    });
    box.appendChild(row);
  });
  // llama.cpp 状态
  const L = embedCfg.llama;
  $("llama-state").innerHTML = L.ready
    ? `<span style="color:var(--ok)">✓ 就绪</span>`
    : `<span style="color:var(--err)">✗ 未就绪（缺 ${!L.exe ? "llama-server.exe" : "GGUF 模型"}）</span>`;
  $("llama-info").innerHTML =
    `<div class="row"><span class="muted">服务端</span><span style="font-size:11px">${escapeHtml(L.exe || "未找到（放入 dist/llama/ 或设 RAG_LLAMA_EXE）")}</span></div>` +
    `<div class="row"><span class="muted">模型</span><span style="font-size:11px">${escapeHtml(L.gguf || "未下载")}</span></div>`;
  // GGUF 列表
  knownGgufs = (embedCfg.ggufs || []).map((f) => f.file);
  const g = $("gguf-list");
  g.innerHTML = "";
  (embedCfg.ggufs || []).forEach((f) => {
    const active = f.file === L.gguf;
    const row = document.createElement("div");
    row.className = "provider" + (active ? " active" : "");
    row.innerHTML =
      `<div class="p-body"><div class="p-name">${escapeHtml(f.file)}</div></div>` +
      `<span class="p-tag muted">${f.size_mb} MB</span>` +
      (active ? `<span class="p-tag">● 使用中</span>` : ``);
    row.addEventListener("click", async () => {
      try {
        const r = await post("/api/embed/gguf/select", { file: f.file });
        if (r.warning) alert(r.warning);
        else alert(`✓ 已切换为 ${f.file}\n嵌入服务已重启，下次检索按新模型生效`);
      } catch (e) { alert("切换失败: " + e.message); }
      renderEmbed();
    });
    g.appendChild(row);
  });
  renderDl();
}

let dlPolling = false;
function renderDl() {
  api("/api/embed/hf/status").then((s) => {
    document.querySelectorAll("#hf-files .provider").forEach((row) => {
      const btn = row.querySelector("[data-hf]");
      const bar = row.querySelector(".dl-bar");
      if (!btn || !bar) return;
      const active = s.running && s.file === btn.dataset.hf;
      bar.style.display = active ? "block" : "none";
      btn.disabled = !!s.running;
      btn.textContent = active ? "下载中" : "下载";
      if (active) {
        bar.firstElementChild.style.width = (s.pct || 0) + "%";
        let info = row.querySelector(".dl-info");
        if (!info) { info = document.createElement("span"); info.className = "dl-info"; row.appendChild(info); }
        info.textContent = `${((s.downloaded || 0) / 1e6).toFixed(0)}/${((s.total || 0) / 1e6).toFixed(0)}MB · ${s.speed_mbs || 0}MB/s`;
      }
    });
    const q = $("dl-queue");
    if (q) q.textContent = s.running
      ? `⏬ ${s.file} · ${s.pct}% · ${((s.downloaded || 0) / 1e6).toFixed(0)}/${((s.total || 0) / 1e6).toFixed(0)}MB · ${s.speed_mbs || 0}MB/s`
      : (dlPolling ? "✓ 下载完成" : "");
    if (s.running) { dlPolling = true; setTimeout(renderDl, 800); }
    else if (dlPolling) { dlPolling = false; renderEmbed(); }   // 完成刷新已下载列表
  }).catch(() => {});
}

const quantOf = (f) => ((f.match(/(IQ\d_\w+|Q\d_K_S?|Q\d_K_M|Q\d_0|Q\d|f16|bf16)/i) || [""])[0]).toUpperCase();

function renderHfFiles() {
  const box = $("hf-files");
  if (!hfFiles.length) { box.innerHTML = `<span class="empty">（无 GGUF 文件）</span>`; return; }
  box.innerHTML = "";
  hfFiles.forEach((f) => {
    const downloaded = knownGgufs.includes(f.file);
    const q = quantOf(f.file);
    const row = document.createElement("div");
    row.className = "provider";
    row.innerHTML =
      `<div class="p-body"><div class="p-name">${escapeHtml(f.file)}</div></div>` +
      (q ? `<span class="qbadge">${q}</span>` : ``) +
      `<span class="p-tag muted">${f.size_mb} MB</span>` +
      (downloaded ? `<span class="p-tag" style="color:var(--green)">✓ 已下载</span>`
                  : `<button class="primary" data-hf="${escapeHtml(f.file)}" style="padding:4px 12px">下载</button>`) +
      `<div class="dl-bar" style="display:none;min-width:150px"><div></div></div>`;
    const btn = row.querySelector("[data-hf]");
    if (btn) btn.addEventListener("click", async (e) => {
      e.stopPropagation();
      btn.disabled = true; btn.textContent = "下载中";
      try {
        const r = await post("/api/embed/hf/download",
          { repo: $("hf-repo").value.trim(), file: f.file, mirror: $("hf-mirror").checked });
        if (!r.ok) { alert(r.message); btn.disabled = false; btn.textContent = "下载"; return; }
        renderDl();
      } catch (err) { alert(err.message); btn.disabled = false; btn.textContent = "下载"; }
    });
    box.appendChild(row);
  });
  renderDl();
}

async function hfSearch() {
  const kw = $("hf-kw").value.trim();
  if (!kw) return;
  const box = $("hf-files");
  box.innerHTML = `<span class="empty">🔍 搜索中（经本地后端 · 在线数据）…</span>`;
  try {
    const r = await api(`/api/embed/hf/search?kw=${encodeURIComponent(kw)}&mirror=${$("hf-mirror")?.checked !== false}`);
    hfFiles = [];
    box.innerHTML = "";
    (r.repos || []).forEach((rep) => {
      const row = document.createElement("div");
      row.className = "provider";
      row.innerHTML =
        `<div class="p-body"><div class="p-name">${escapeHtml(rep.id)}</div>` +
        `<span class="p-tag muted">↓${fmtW(rep.downloads || 0)}</span>` +
        `<span class="p-tag">查看文件</span>`;
      row.addEventListener("click", async () => {
        $("hf-repo").value = rep.id;
        box.innerHTML = `<span class="empty">拉取文件列表中…</span>`;
        try {
          const f = await api(`/api/embed/hf/files?repo=${encodeURIComponent(rep.id)}&mirror=${$("hf-mirror")?.checked !== false}`);
          hfFiles = f.files || [];
          renderHfFiles();
        } catch (e) { box.innerHTML = `<span class="empty">✗ ${escapeHtml(e.message)}</span>`; }
      });
      box.appendChild(row);
    });
    if (!box.children.length) box.innerHTML = `<span class="empty">无匹配仓库</span>`;
  } catch (e) { box.innerHTML = `<span class="empty">✗ ${escapeHtml(e.message)}</span>`; }
}

async function loadPrefs() {
  try {
    const pf = await api("/api/prefs");
    $("pref-temp").value = pf.temperature ?? 0.3;
    $("pref-topk").value = pf.top_k ?? 6;
    if ($("pref-threads")) $("pref-threads").value = pf.threads ?? 16;
  } catch (_) {}
}
$("btn-pref-save").addEventListener("click", async () => {
  try {
    const body = {
      temperature: parseFloat($("pref-temp").value),
      top_k: parseInt($("pref-topk").value, 10),
    };
    if ($("pref-threads") && $("pref-threads").value) body.threads = parseInt($("pref-threads").value, 10);
    await post("/api/prefs", body);
    if (body.threads) setMsgAuto("threads-msg", "✓ 线程已应用（新加载的模型生效）", true, 5000);
    setMsgAuto("pref-msg", "✓ 已保存", true);
  } catch (e) { setMsg("pref-msg", e.message, false); }
});

/* 应用线程（独立按钮——此前从未绑定事件，点了没反应） */
$("btn-threads-save").addEventListener("click", async () => {
  const v = parseInt($("pref-threads").value, 10);
  if (!v || v < 1 || v > 32) { setMsg("threads-msg", "线程数需为 1~32", false); return; }
  try {
    await post("/api/prefs", { threads: v });
    setMsgAuto("threads-msg", "✓ 已应用（索引/检索编码生效）", true);
  } catch (e) { setMsg("threads-msg", e.message, false); }
});

function openModelsGen() { nav("models-gen"); }

/* 新增/修改生成档案 */
$("btn-np-save").addEventListener("click", async () => {
  const name = $("np-name").value.trim(), url = $("np-url").value.trim(), model = $("np-model").value.trim();
  const key = $("np-key").value.trim();
  if (!name || !url) { alert("名称与 URL 必填"); return; }
  try {
    await post("/api/providers", { name, url, model, key: key || undefined });
    $("np-name").value = $("np-url").value = $("np-model").value = "";
    renderProviders(); refreshStatus();
  } catch (e) { alert(e.message); }
});

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

/* Embedding 端点档案新增 */
let hfFiles = [];
let knownGgufs = [];   // 已下载模型清单（标记文件行，防重复下载）
const EMBED_PRESETS = [
  { name: "LM Studio", url: "http://127.0.0.1:1234/v1/embeddings", model: "text-embedding-qwen3-embedding-0.6b" },
  { name: "llama-server 内置", url: "http://127.0.0.1:18900/v1/embeddings", model: "qwen3" },
  { name: "硅基流动 Qwen3", url: "https://api.siliconflow.cn/v1/embeddings", model: "Qwen/Qwen3-Embedding-0.6B" },
];
(function renderEmbedQuick() {
  const box = $("ep-quick");
  box.innerHTML = `<span class="muted small">快捷填入：</span>` + EMBED_PRESETS.map(
    (p, i) => `<button class="chip" data-ep="${i}">${p.name}</button>`).join("");
  box.querySelectorAll("[data-ep]").forEach((b) => b.addEventListener("click", () => {
    const p = EMBED_PRESETS[b.dataset.ep];
    $("ep-name").value = p.name; $("ep-url").value = p.url; $("ep-model").value = p.model;
  }));
})();

$("btn-ep-save").addEventListener("click", async () => {
  const name = $("ep-name").value.trim(), url = $("ep-url").value.trim(),
        model = $("ep-model").value.trim(), key = $("ep-key").value.trim();
  if (!name || !url) { alert("名称与 URL 必填"); return; }
  try {
    const cfg = await api("/api/embed/config");
    const profiles = (cfg.http_profiles || []).filter((p) => p.name !== name);
    const prof = { name, url, model };
    if (key) prof.key = key;
    profiles.push(prof);
    await post("/api/embed/config", { http_profiles: profiles, http_active: name });
    $("ep-key").value = "";
    renderEmbed();
  } catch (e) { alert(e.message); }
});

/* HF GGUF 下载 */
$("btn-hf-search").addEventListener("click", hfSearch);
$("hf-kw").addEventListener("keydown", (e) => { if (e.key === "Enter") hfSearch(); });

async function hfFilesDirect(repo, box) {
  /* 按仓库 id 直达文件列表；成功返回 true（失败不报错，交给调用方兜底） */
  box.innerHTML = `<span class="empty">按仓库 id 拉取文件列表中…</span>`;
  try {
    const r = await api(`/api/embed/hf/files?repo=${encodeURIComponent(repo)}&mirror=${$("hf-mirror")?.checked !== false}`);
    hfFiles = r.files || [];
    renderHfFiles();
    return true;
  } catch (_) { return false; }
}

async function hfBrowse() {
  /* 智能路由：像仓库 id（含 /）先直达，失败自动转关键词搜索；纯关键词直接搜 */
  const v = $("hf-repo").value.trim();
  const box = $("hf-files");
  if (!v) return;
  if (v.includes("/")) {
    if (await hfFilesDirect(v, box)) return;
    box.innerHTML = `<span class="empty">仓库 id 未命中（不存在/无 GGUF），自动转关键词搜索…</span>`;
    $("hf-kw").value = v.split("/").pop() || v;   // 去掉所有者前缀，否则 HF 搜索必然零匹配
  } else {
    $("hf-kw").value = v;
  }
  await hfSearch();
}

$("btn-hf-list").addEventListener("click", hfBrowse);
$("hf-repo").addEventListener("keydown", (e) => { if (e.key === "Enter") hfBrowse(); });

async function loadHfFiles() {
  const box = $("hf-files");
  box.innerHTML = `<span class="empty">拉取中…</span>`;
  try {
    const r = await api(`/api/embed/hf/files?repo=${encodeURIComponent($("hf-repo").value.trim())}&mirror=${$("hf-mirror").checked}`);
    hfFiles = r.files || [];
    renderHfFiles();
  } catch (e) { box.innerHTML = `<span class="empty">✗ ${escapeHtml(e.message)}</span>`; }
}


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
    .replace(/\*\*/g, "")          // 模型输出的孤立 ** 不再显示为字面量
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
const fmtW = n => n >= 1000 ? (n / 1000).toFixed(1) + "k" : String(n);
const escapeHtml = (s) => String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/* ================= 侧边分级导航 ================= */
const TITLES = { chat: "问答（检索）", board: "看板", ops: "索引 · 范围 · 上传",
                 repos: "仓库管理（多 RAG）", index: "索引与范围",
                 "models-gen": "生成供应商", "models-emb": "检索 Embedding",
                 mcp: "MCP & 状态", settings: "高级设置" };
function nav(name) {
  document.querySelectorAll(".nav-item").forEach((b) =>
    b.classList.toggle("active", b.dataset.nav === name));
  document.querySelectorAll(".panel").forEach((p) => p.classList.remove("active"));
  $("panel-" + name).classList.add("active");
  $("page-title").textContent = TITLES[name] || name;
  const loaders = {
    board: loadBoard, repo: loadRepo, index: loadManage, ops: loadManage,
    "models-gen": () => renderProviders(),
    "models-emb": () => renderEmbed(),
    settings: async () => { await loadPrefs(); await loadSettingsInfo(); },
    mcp: async () => { await loadMcpStatus(); await loadClients(); },
    repos: loadRepos,
  };
  if (loaders[name]) Promise.resolve(loaders[name]()).catch(e => console.error(name, e));
  closeNavOnSmall();
}
function closeNavOnSmall() {
  if (window.innerWidth <= 900) document.body.classList.remove("nav-open");
}
document.querySelectorAll(".nav-item").forEach((btn) =>
  btn.addEventListener("click", () => nav(btn.dataset.nav)));

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
    const msg = `${st.notes} 篇 · ${st.chunks} 块 · ${st.db_mb}MB` + (ok ? "" : " · 库不一致!");
    document.getElementById("status-text").textContent = msg;
    $("topbar-info").textContent = msg;
    $("topbar-info").title = "上次索引: " + st.last_indexed + "\n检索向量: " + (st.embed_ready ? "在线" : "离线(关键词模式)") + "\n生成: " + st.chat_model + (st.chat_ready ? " ✓" : " 缺key");
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

function renderSources(results, mm) {
  $("sources-count").textContent = results.length ? `(${results.length})` : "";
  const box = $("sources-list");
  box.innerHTML = "";
  if (!results.length && !(mm && mm.length)) {
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
  if (mm && mm.length) {
    const head = document.createElement("div");
    head.className = "mh-item muted";
    head.style.margin = "6px 0 2px";
    head.textContent = "PDF/PPT 页命中（可转笔记）";
    box.appendChild(head);
    mm.forEach((m) => {
      const d = document.createElement("div");
      d.className = "source glass";
      d.innerHTML =
        `<span class="score">${m.score?.toFixed(3) ?? ""}</span>` +
        `<b>📄</b> <span class="path">${escapeHtml(m.label)}</span>` +
        ` <button class="linklike" data-mm-note="${m.chunk_id}">转笔记</button>`;
      d.querySelector("[data-mm-note]").addEventListener("click", async (e) => {
        e.stopPropagation();
        try {
          const r = await post("/api/mm/to-note", { chunk_id: m.chunk_id });
          alert("已转笔记：" + r.note);
        } catch (err) { alert(err.message); }
      });
      box.appendChild(d);
    });
  }
}

function copyBtnHtml() {
  return `<button class="copy-btn" data-copy title="复制回答">⧉ 复制</button>`;
}
$("chat-log").addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-copy]");
  if (!btn) return;
  const bubble = btn.closest(".bubble");
  const text = (bubble?.innerText || "").replace(/\s*⧉ 复制\s*$/, "");
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = "✓ 已复制";
    setTimeout(() => { btn.textContent = "⧉ 复制"; }, 1600);
  } catch (_) {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
    btn.textContent = "✓ 已复制";
    setTimeout(() => { btn.textContent = "⧉ 复制"; }, 1600);
  }
});

function setBusy(busy) {
  $("btn-send").disabled = busy;
  $("btn-search-only").disabled = busy;
}

async function sendChat(searchOnly) {
  if ($("btn-send").disabled) return;          // 防连点并发流
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
      if (out.mode === "keyword") {
        bubble.innerHTML += `<p class="mode-note">ℹ 当前为关键词检索 · 启动 LM Studio(1234) 后自动升级语义检索</p>`;
      }
      if (!out.results.length) bubble.innerHTML = md("没有检索到相关内容。");
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
        buf += dec.decode(value, { stream: true }).split("\r\n").join("\n");
        let idx;
        while ((idx = buf.indexOf("\n\n")) >= 0) {
          const line = buf.slice(0, idx).trim();
          buf = buf.slice(idx + 2);
          if (!line.startsWith("data:")) continue;
          let ev;
          try { ev = JSON.parse(line.slice(5)); } catch (_) { continue; }
          if (ev.type === "sources") {
            renderSources(ev.results, ev.mm);
          } else if (ev.type === "delta") {
            acc += ev.text;
            bubble.innerHTML = md(acc) + caret + copyBtnHtml();
            $("chat-log").scrollTop = $("chat-log").scrollHeight;
          } else if (ev.type === "warning") {
            acc += `\n\n⚠ ${ev.message}`;
            bubble.innerHTML = md(acc);
          } else if (ev.type === "info") {
            bubble.innerHTML = md(acc || "") +
              `<p class="mode-note">ℹ ${escapeHtml(ev.message)}</p>` + caret;
          } else if (ev.type === "fallback") {
            renderSources(ev.results);
            bubble.innerHTML =
              `<span class="fallback-note">⚠ AI 生成不可用：${escapeHtml(ev.message)}<br>` +
              `→ <button class="linklike" data-open-settings>到「生成供应商」粘贴 Key</button>` +
              `（检索不受影响，当前展示本地检索结果）</span>` +
              md("以下为本地检索结果（右侧可打开原文）：");
          } else if (ev.type === "error") {
            bubble.innerHTML = md(acc || "") + `<span class="fallback-note">✗ 出错: ${escapeHtml(ev.message)}</span>`;
          }
        }
      }
      bubble.innerHTML = md(acc) + copyBtnHtml();
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
  if (e.target.closest("[data-open-settings]")) nav("models-gen");
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
    const [st, d, hl] = await Promise.all([api("/api/status"), api("/api/dashboard"),
                                           api("/api/headline").catch(() => null)]);
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

    /* ---- 报纸头条 ---- */
    if (hl) {
      $("mh-date").textContent = hl.date;
      const L = hl.latest;
      $("mh-headline").innerHTML = L
        ? `<span class="mh-tag">${escapeHtml(L.client)}</span> ${escapeHtml(L.action)} <b>${escapeHtml(L.path)}</b>` +
          `<span class="muted small"> · ${escapeHtml((L.ts || "").slice(11))}</span>`
        : `暂无代理动作——你的 AI 们还没写过记忆，等它们开工`;
      $("mh-feed").innerHTML = hl.feed.length ? hl.feed.map((e) =>
        `<div class="mh-item"><span class="muted">${escapeHtml((e.ts || "").slice(5, 16))}</span> ` +
        `${escapeHtml(e.action)} <span title="${escapeHtml(e.path)}">${escapeHtml(e.path)}</span></div>`).join("")
        : `<span class="empty">暂无</span>`;
      $("mh-new").innerHTML =
        `<div class="mh-item"><b>${hl.new_7d}</b> 篇新增</div>` +
        (hl.recent_notes || []).map((p) =>
          `<div class="mh-item" title="${escapeHtml(p)}">${escapeHtml(p)}</div>`).join("");
      $("mh-due").innerHTML = hl.due_reviews.length ? hl.due_reviews.map((m) =>
        `<div class="mh-item">📕 <span title="${escapeHtml(m.rel)}">${escapeHtml(m.rel)}</span>` +
        `<span class="muted">${escapeHtml(m.subject)}</span></div>`).join("")
        : `<span class="empty">无到期复习 · 复利进行中</span>`;
    }
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
    $("settings-info").innerHTML =
      `<div class="row"><span class="muted">Key</span><span>${cfg.key_set ? "✓ 已配置" : "✗ 未配置"}</span></div>` +
      `<div class="row"><span class="muted">模型</span><span>${escapeHtml(cfg.model)}</span></div>` +
      `<div class="row"><span class="muted">端点</span><span style="font-size:11px;word-break:break-all">${escapeHtml(cfg.endpoint)}</span></div>`;
    try {
      const bi = await api("/api/backend/info");
      $("backend-url").value = `${location.origin}/v1`;
      $("backend-key").value = bi.key;
    } catch (_) { /* 后端信息失败不阻塞设置页 */ }
    try {                                   // 识图策略 + 价格估算 + 上次校准
      const ms = await api("/api/mm/strategy");
      if ($("mm-strategy")) $("mm-strategy").value = ms.strategy;
      const pr = await api("/api/mm/prices?pages=100");
      const e = pr.estimate;
      $("mm-price").textContent =
        `100 页估算 — 纯本地: ¥0 · 云描述(${e.cloud_free_model}): $${(e.cloud_free_per_n || 0).toFixed(3)}` +
        ` · 高性能(${e.cloud_pro_model}): $${(e.cloud_pro_per_n || 0).toFixed(2)}`;
      const cb = await api("/api/mm/calibrate");
      if (cb.result && $("mm-msg"))
        $("mm-msg").textContent =
          `上次校准: 本地 ${cb.result.local.pass}/${cb.result.local.n} · 云端 ${cb.result.cloud.pass}/${cb.result.cloud.n}（${cb.result.time}）`;
    } catch (_) { /* 多模态信息失败不阻塞 */ }
    pollIndex();
  } catch (e) { setMsg("scope-msg", e.message, false); }
}

$("btn-backend-copy").addEventListener("click", async () => {
  const cfg = { name: "vault-rag", base_url: $("backend-url").value,
                api_key: $("backend-key").value, model: "vault-rag" };
  try {
    await navigator.clipboard.writeText(JSON.stringify(cfg, null, 2));
    setMsgAuto("backend-msg", "✓ 已复制接入配置 JSON", true);
  } catch (e) { setMsg("backend-msg", e.message, false); }
});

$("mm-strategy").addEventListener("change", async (e) => {
  try {
    await post("/api/mm/strategy", { strategy: e.target.value });
    setMsgAuto("mm-msg", "✓ 策略已保存（下次识图生效）", true);
  } catch (err) { setMsg("mm-msg", err.message, false); }
});

$("btn-mm-calib").addEventListener("click", async () => {
  try {
    await post("/api/mm/calibrate");
    setMsgAuto("mm-msg", "校准中：本地模型加载 + 4 合成案例（约 1-2 分钟）…", true, 300000);
    const poll = setInterval(async () => {
      try {
        const r = await api("/api/mm/calibrate");
        if (!r.calibrating && r.result) {
          clearInterval(poll);
          $("mm-msg").className = "msg ok";
          $("mm-msg").textContent =
            `✓ 校准完成 — 本地 ${r.result.local.pass}/${r.result.local.n} · 云端 ${r.result.cloud.pass}/${r.result.cloud.n}`;
        }
      } catch (_) { clearInterval(poll); }
    }, 3000);
  } catch (err) { setMsg("mm-msg", err.message, false); }
});

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
      const bar = $("index-pbar"), pct = $("index-pct");
      if (st.running) {
        state.textContent = `运行中 ${st.elapsed}s · 待索引 ${st.pending < 0 ? "?" : st.pending} 篇`;
        $("index-log").className = "log busy";
        $("index-log").textContent = st.log || "（编码中…）";
        $("index-log").scrollTop = $("index-log").scrollHeight;
        // 从日志解析 [n/total] 篇进度
        const m = (st.log || "").match(/\[(\d+)\/(\d+)\]/g);
        let p = 0;
        if (m && m.length) {
          const last = m[m.length - 1].match(/\[(\d+)\/(\d+)\]/);
          if (last) p = Math.round(Number(last[1]) / Number(last[2]) * 100);
        }
        if (bar) bar.firstElementChild.style.width = p + "%";
        if (pct) pct.textContent = p + "%";
      } else {
        state.textContent = `待索引 ${st.pending < 0 ? "?" : st.pending} 篇` +
          (st.finished ? ` · 上次${st.ok === false ? " ✗失败" : " ✓完成"}` : "");
        if (bar) bar.firstElementChild.style.width = "100%";
        if (pct) pct.textContent = "✓";
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

$("modal-key-save").addEventListener("click", async () => {
  const v = $("modal-key").value.trim();
  if (!v) { setMsgAuto("key-msg", "输入为空，未保存", false); return; }
  try {
    const r = await post("/api/settings", { agnes_key: v });
    $("modal-key").value = "";
    setMsgAuto("key-msg", r.key_set ? "✓ Key 已保存" : "保存失败", r.key_set);
    refreshStatus();
  } catch (e) { setMsg("key-msg", e.message, false); }
});

/* ================= 启动 ================= */
refreshStatus();
setInterval(refreshStatus, 10000);
loadManage();

/* ================= 仓库管理 ================= */
let repoPage = 1;
async function loadRepo() {
  try {
    const s = await api("/api/repo/stats");
    const d = await api("/api/repo/notes?page=1&size=15");
    await renderRepo(s, d);
  } catch (e) {
    $("repo-cards").innerHTML = `<div class="card bad"><div class="num">✗</div><div class="lbl">${escapeHtml(e.message)}</div></div>`;
  }
}
async function loadRepoPage(page = 1) {
  const q = $("repo-q").value.trim();
  const domain = $("repo-domain").value;
  const d = await api(`/api/repo/notes?q=${encodeURIComponent(q)}&domain=${encodeURIComponent(domain)}&page=${page}&size=15`);
  const s = await api("/api/repo/stats");
  await renderRepo(s, d);
}
async function renderRepo(s, d) {
  repoPage = d.page;
  const cards = [
    ["笔记", s.notes, ""], ["文本块", s.chunks, ""],
    ["向量", s.vectors, s.consistent ? "" : "不一致!"],
    ["embed 缓存", s.embed_cache, ""], ["库大小", s.db_mb + "MB", ""],
  ];
  $("repo-cards").innerHTML = cards.map(([lbl, num, err]) =>
    `<div class="card glass ${err ? "bad" : ""}"><div class="num">${num}</div>` +
    `<div class="lbl">${lbl}${err ? " · " + err : ""}</div></div>`).join("");
  $("repo-total").textContent = `共 ${d.total} 篇`;
  const sel = $("repo-domain");
  const cur = sel.value;
  sel.innerHTML = `<option value="">全部领域</option>` +
    d.domains.map((x) => `<option ${x === cur ? "selected" : ""}>${escapeHtml(x)}</option>`).join("");
  $("repo-notes").innerHTML = d.notes.length ? d.notes.map((n) =>
    `<div class="row"><a data-path="${escapeHtml(n.rel_path)}" title="${escapeHtml(n.rel_path)}">${escapeHtml(n.rel_path)}</a>` +
    `<span class="time">${n.chunks}块/${n.vectors}向量</span>` +
    `<span class="time">${n.mtime_str}</span>` +
    `<button class="p-del" data-del="${escapeHtml(n.rel_path)}">移出索引</button></div>`).join("")
    : `<span class="empty">无匹配笔记</span>`;
  $("repo-page").textContent = `${d.page} / ${d.pages}`;
  $("repo-notes").querySelectorAll("a").forEach((a) =>
    a.addEventListener("click", () =>
      post("/api/open", { rel_path: a.dataset.path }).catch((e) => alert(e.message))));
  $("repo-notes").querySelectorAll("[data-del]").forEach((b) =>
    b.addEventListener("click", async () => {
      if (!confirm(`把「${b.dataset.del}」移出索引？\n（vault 原文不受影响，下次增量索引会重新收录）`)) return;
      try {
        await api("/api/repo/notes", { method: "DELETE",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ rel_path: b.dataset.del }) });
        loadRepoPage(repoPage);
      } catch (e) { alert(e.message); }
    }));
}
$("btn-repo-search").addEventListener("click", () => loadRepoPage(1));
$("repo-q").addEventListener("keydown", (e) => { if (e.key === "Enter") loadRepoPage(1); });
$("repo-prev").addEventListener("click", () => repoPage > 1 && loadRepoPage(repoPage - 1));
$("repo-next").addEventListener("click", () => loadRepoPage(repoPage + 1));
$("repo-domain").addEventListener("change", () => loadRepoPage(1));

$("btn-clear-cache").addEventListener("click", async () => {
  if (!confirm("清空全部 embedding KV 缓存？\n（检索不受影响；下次重建索引将重新编码全部文本）")) return;
  try {
    const r = await post("/api/repo/clear-cache");
    setMsgAuto("repo-op-msg", `✓ 已清空 ${r.cleared} 条缓存`, true);
    loadRepo();
  } catch (e) { setMsg("repo-op-msg", e.message, false); }
});
$("btn-vacuum").addEventListener("click", async () => {
  try {
    const r = await post("/api/repo/vacuum");
    setMsgAuto("repo-op-msg", `✓ VACUUM 完成：${r.before_mb}MB → ${r.after_mb}MB`, true);
    loadRepo();
  } catch (e) { setMsg("repo-op-msg", e.message, false); }
});
$("btn-rebuild").addEventListener("click", async () => {
  if (!confirm("清空全部索引并全量重建？\n（KV 缓存保留，未变内容重建很快；vault 原文不受影响）")) return;
  try {
    await post("/api/repo/rebuild");
    setMsgAuto("repo-op-msg", "✓ 索引已清空，正在启动全量重建…", true, 10000);
    await post("/api/index/refresh");
    loadRepo();
  } catch (e) { setMsg("repo-op-msg", e.message, false); }
});

$("btn-selftest").addEventListener("click", async () => {
  $("selftest-msg").textContent = "自检运行中…";
  $("selftest-list").innerHTML = "";
  try {
    const r = await api("/api/selftest");
    $("selftest-msg").textContent = r.ok ? `✓ 全部通过（${r.elapsed_ms}ms）` : `✗ 有 ${r.checks.filter((c) => !c.ok).length} 项未过（${r.elapsed_ms}ms）`;
    $("selftest-list").innerHTML = r.checks.map((c) =>
      `<div class="row"><span style="color:${c.ok ? "var(--green)" : "var(--err)"}">${c.ok ? "✓" : "✗"} ${escapeHtml(c.name)}</span>` +
      `<span class="muted small" style="text-align:right">${escapeHtml(c.detail)}</span></div>`).join("");
  } catch (e) { $("selftest-msg").textContent = "✗ " + e.message; }
});

/* ================= 设置页 ================= */
async function loadSettingsInfo() {
  try {
    const [st, cfg, pf] = await Promise.all([
      api("/api/status"), api("/api/providers"),
      api("/api/prefs").catch(() => ({})),
    ]);
    const prof = cfg.active;
    const rows = [
      ["生成供应商", `${prof.name} · ${prof.model}`],
      ["生成端点", prof.url],
      ["检索链", (pf.top_k ? `top_k=${pf.top_k} · ` : "") + `temperature=${pf.temperature ?? 0.3}`],
      ["检索端点", st.embed_url],
      ["内置 llama.cpp", st.embed_ready ? "（HTTP 在线，未接管）" : (st.embed_ready === false ? "待命/接管中" : "—")],
      ["torch 线程", (pf.threads || 16) + "（可在上方调整）"],
      ["Web 端口", "8765（RAG_WEBUI_PORT 可调）"],
      ["Vault", st.vault],
    ];
    $("settings-info").innerHTML = rows.map(([k, v]) =>
      `<div class="row"><span style="color:var(--muted);min-width:110px">${escapeHtml(k)}</span>` +
      `<span style="font-family:var(--mono);font-size:11.5px;word-break:break-all">${escapeHtml(String(v))}</span></div>`).join("");
  } catch (e) {
    $("settings-info").innerHTML = `<span class="empty">加载失败: ${escapeHtml(e.message)}</span>`;
  }
}

/* ================= 仓库管理（多 RAG 仓库） ================= */
let curRepo = "";
async function loadRepos() {
  try {
    const d = await api("/api/repos");
    curRepo = d.current;
    $("repos-hint").textContent = `当前: ${d.current}`;
    const box = $("repos-list");
    box.innerHTML = "";
    d.repos.forEach((r0) => {
      const row = document.createElement("div");
      row.className = "provider" + (r0.is_current ? " active" : "");
      row.innerHTML =
        `<div class="p-body"><div class="p-name">${escapeHtml(r0.name)}${r0.is_current ? " <span class='p-tag'>● 当前</span>" : ""}</div>` +
        `<div class="p-sub">${escapeHtml(r0.data_dir)}</div></div>` +
        `<span class="p-tag muted">${r0.ready ? (r0.notes !== "?" ? r0.notes + " 篇 · " : "") + r0.size_mb + "MB" : "空仓库"}</span>` +
        (r0.is_current ? `` : `<button class="primary mini" data-switch="${escapeHtml(r0.name)}">切换</button>`);
      const sw = row.querySelector("[data-switch]");
      if (sw) sw.addEventListener("click", async (e) => {
        e.stopPropagation();
        if (!confirm(`切换到仓库「${r0.name}」？\n（问答/看板/仓库页立即跟随；独立 MCP 进程重启后跟随）`)) return;
        try {
          await post("/api/repos/switch", { name: r0.name });
          await loadRepos(); refreshStatus();
        } catch (err) { alert(err.message); }
      });
      box.appendChild(row);
    });
  } catch (e) { $("repos-hint").textContent = "✗ " + e.message; }
}
$("btn-repo-create").addEventListener("click", async () => {
  const name = $("repo-new-name").value.trim();
  if (!name) { setMsgAuto("repo-new-msg", "请输入仓库名", false); return; }
  try {
    const r = await post("/api/repos/create", { name });
    setMsgAuto("repo-new-msg", "✓ 已创建并切换: " + r.data_dir, true, 6000);
    $("repo-new-name").value = "";
    loadRepos(); refreshStatus();
  } catch (e) { setMsg("repo-new-msg", e.message, false); }
});

/* ================= 批量上传 ================= */
const dz = $("dropzone"), upInput = $("upload-input");
dz.addEventListener("click", () => upInput.click());
["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.add("drag");
}));
["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, (e) => {
  e.preventDefault(); dz.classList.remove("drag");
}));
dz.addEventListener("drop", (e) => {
  if (e.dataTransfer.files.length) sendUpload(e.dataTransfer.files);
});
upInput.addEventListener("change", () => {
  if (upInput.files.length) sendUpload(upInput.files);
  upInput.value = "";
});
async function sendUpload(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  const imgs = files.filter((f) => (f.type || "").startsWith("image/"));
  const docs = files.filter((f) => !(f.type || "").startsWith("image/"));
  $("upload-result").className = "msg muted";
  $("upload-result").textContent = `处理中（${files.length} 个文件，图片走错题识别）…`;
  const out = { mistakes: [], mkErr: [], saved: [], skipped: [], batch: "" };
  try {
    for (const f of imgs) {
      const fd = new FormData(); fd.append("file", f);
      const r = await fetch("/api/mistake/ingest", { method: "POST", body: fd });
      const d = await r.json().catch(() => ({}));
      if (r.ok && d.ok) out.mistakes.push(d);
      else out.mkErr.push(`${f.name}（${d.detail || r.statusText}）`);
    }
    if (docs.length) {
      const fd = new FormData();
      docs.forEach((f) => fd.append("files", f));
      const r = await fetch("/api/upload", { method: "POST", body: fd });
      const d = await r.json();
      if (!r.ok) throw new Error(d.detail || r.statusText);
      out.saved = d.saved; out.skipped = d.skipped; out.batch = d.batch_dir;
      out.mmFiles = d.mm_files || [];
    }
    const parts = [];
    if (out.mistakes.length)
      parts.push(`📸 错题 ${out.mistakes.length} 篇已入库（${
        out.mistakes.map((m) => m.note_rel).join("；")})`);
    if (out.saved.length) parts.push(`✓ 文档 ${out.saved.length} 个已入库`);
    if (out.skipped.length) parts.push(`跳过: ${out.skipped.join("；")}`);
    if (out.mkErr.length) parts.push(`错题失败: ${out.mkErr.join("；")}`);
    const okAny = out.mistakes.length + out.saved.length > 0;
    $("upload-result").className = okAny ? "msg ok" : "msg err";
    $("upload-result").textContent = (okAny ? "✓ " : "✗ ") +
      (parts.join("　") || "没有文件入库");
    $("upload-actions").style.display = okAny ? "flex" : "none";
    $("upload-batchdir").textContent = out.batch;
    $("btn-upload-index").onclick = async () => {
      $("upload-actions").style.display = "none";
      await post("/api/index/refresh");
      nav("ops"); pollIndex();
    };
    // PDF/PPTX → 多模态一键管线（后台线程 + 轮询进度）
    if ((out.mmFiles || []).length) {
      for (const p of out.mmFiles) await post("/api/mm/ingest", { path: p });
      await pollMm();
    }
  } catch (e) {
    $("upload-result").className = "msg err";
    $("upload-result").textContent = "✗ " + e.message;
  }
}

async function pollMm() {
  let started = false, waited = 0;
  for (;;) {
    const s = await api("/api/mm/status").catch(() => null);
    if (!s) return;
    if (s.running) started = true;
    // 线程尚未写入状态时给 12s 宽限，避免抢跑误报"完成 0 页"
    if (!s.running && (started || s.ok !== null || s.file)) {
      const name = (s.file || "").split(/[\\/]/).pop();
      $("upload-result").className = s.ok === false ? "msg err" : "msg ok";
      $("upload-result").textContent = s.ok === false
        ? `✗ 识图处理失败：${name} ${s.log || ""}`
        : `✓ 识图完成：${name} ${s.total} 页入库（策略 ${s.strategy}，可检索）`;
      return;
    }
    waited += 1500;
    if (waited > 12000) return;
    $("upload-result").className = "msg muted";
    $("upload-result").textContent = "⚙ 识图管线启动中…";
    await new Promise((r) => setTimeout(r, 1500));
  }
}

/* ================= MCP & 状态 ================= */
async function loadClients() {
  const box = $("clients-list");
  box.innerHTML = `<span class="empty">检测中…</span>`;
  try {
    const d = await api("/api/mcp/clients");
    box.innerHTML = "";
    d.clients.forEach((c) => {
      const row = document.createElement("div");
      row.className = "provider" + (c.registered ? " active" : "");
      row.innerHTML =
        `<div class="p-body"><div class="p-name">${escapeHtml(c.name)}` +
        (c.registered ? ` <span class="p-tag">● 已接入</span>` : ``) +
        `</div><div class="p-sub">${escapeHtml(c.config_path)}${c.config_found ? "" : "（未检测到，接入时自动创建）"}</div></div>` +
        (c.registered
          ? `<span class="tag use">✓</span>`
          : `<button class="primary mini" data-reg="${c.id}">一键接入</button>`);
      const reg = row.querySelector("[data-reg]");
      if (reg) reg.addEventListener("click", async (e) => {
        e.stopPropagation();
        reg.disabled = true; reg.textContent = "写入中…";
        try {
          await post("/api/mcp/clients/register", { client: c.id });
          reg.outerHTML = `<span class="tag use">✓ 已接入</span>`;
        } catch (err) { alert(err.message); reg.disabled = false; reg.textContent = "一键接入"; }
      });
      box.appendChild(row);
    });
    // DeepSeek Harness / OpenClaw / Pi 未检测到时给片段兜底
    const noCfg = d.clients.filter(c => !c.config_found && !c.registered);
    if (noCfg.length) {
      const d2 = document.createElement("details");
      d2.className = "add-box";
      d2.innerHTML = `<summary>未检测到配置的客户端 · 手动复制片段</summary>` +
        noCfg.map(c => `<div class="row"><b class="small">${escapeHtml(c.name)}</b></div>` +
          `<pre class="log" style="height:auto">${escapeHtml(c.snippet)}</pre>`).join("");
      box.appendChild(d2);
    }
  } catch (e) { box.innerHTML = `<span class="empty">✗ ${escapeHtml(e.message)}</span>`; }
}

async function loadMcpStatus() {
  try {
    const [s, st] = await Promise.all([api("/api/mcp/status"), api("/api/status")]);
    const box = $("mcp-list");
    box.innerHTML = "";
    s.servers.forEach((m) => {
      const row = document.createElement("div");
      row.className = "provider" + (m.registered ? " active" : "");
      row.innerHTML =
        `<div class="p-body"><div class="p-name">${escapeHtml(m.name)}${m.registered ? " <span class='p-tag'>● 已注册</span>" : " <span class='p-tag muted'>未注册</span>"}</div>` +
        `<div class="p-sub">${escapeHtml(m.cmd + " " + m.args)}</div></div>`;
      box.appendChild(row);
    });
    const ro = s.servers.find(x => x.name === "rag-obsidian");
    $("mcp-reg-msg").textContent = "";
    $("settings-info") && 0; // noop
    const sys = $("mcp-sysinfo");
    sys.innerHTML =
      row2("当前仓库", st.notes + " 篇 · " + st.chunks + " 块" + (st.consistent ? " ✓" : " ✗不一致")) +
      row2("检索向量", st.embed_url + (st.embed_ready ? "（在线）" : "（离线→关键词）")) +
      row2("生成供应商", st.chat_model + (st.chat_ready ? " ✓" : "（缺 key）")) +
      row2("rag-obsidian 服务", s.rag_obsidian_exists ? "存在（注入版 32 工具）" : "不存在") +
      "";
    function row2(k, v) {
      return `<div class="row"><span style="color:var(--muted);min-width:120px">${escapeHtml(k)}</span>` +
             `<span style="font-family:var(--mono);font-size:11.5px;word-break:break-all">${escapeHtml(String(v))}</span></div>`;
    }
    sys.querySelectorAll(".row span:last-child").forEach(x => { if (x.textContent === "undefined") x.textContent = "—"; });
  } catch (e) { $("mcp-sysinfo").innerHTML = `<span class="empty">✗ ${escapeHtml(e.message)}</span>`; }
}
$("btn-mcp-refresh").addEventListener("click", loadMcpStatus);

$("btn-mcp-register").addEventListener("click", async () => {
  if (!confirm("把 vault-rag MCP 注册进 Claude Code（~/.claude.json，自动备份）？\n注册后需重启 Claude Code 生效。")) return;
  try {
    const r = await post("/api/mcp/register-vaultrag");
    setMsgAuto("mcp-reg-msg", "✓ 已注册（重启 Claude Code 生效）", true, 6000);
    loadMcpStatus();
  } catch (e) { setMsg("mcp-reg-msg", e.message, false); }
});

$("btn-mcp-test").addEventListener("click", async () => {
  const el = $("mcp-test-msg");
  el.className = "msg muted"; el.textContent = "协议测试运行中（约 10~30 秒）…";
  try {
    const r = await post("/api/mcp/protocol-test", { server: "rag" });
    el.className = "msg " + (r.ok ? "ok" : "err");
    el.textContent = (r.ok ? "✓ " : "✗ ") + r.detail;
  } catch (e) { el.textContent = "✗ " + e.message; el.className = "msg err"; }
});
