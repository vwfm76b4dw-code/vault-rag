# -*- coding: utf-8 -*-
"""一次性补丁：demo 下载页接入真实模型搜索（本地后端优先，离线目录兜底）。"""
from pathlib import Path
import re

p = Path("docs/model_manager_demo.html")
t = p.read_text(encoding="utf-8")

# 1) HTML：加搜索行
old_html = '''          <div class="row">
            <input id="hf-repo" style="flex:1" value="Qwen/Qwen3-Embedding-0.6B-GGUF"
                   placeholder="仓库 id，如 Qwen/Qwen3-Embedding-0.6B-GGUF">
            <label class="chip on" id="hf-mirror">hf-mirror 镜像</label>
            <button class="primary" id="hf-browse">浏览文件</button>
          </div>'''
new_html = '''          <div class="row">
            <input id="hf-kw" style="flex:1"
                   placeholder="搜索模型：关键词（qwen3 embedding）或仓库 id（Qwen/…-GGUF）">
            <button class="primary" id="hf-search">🔍 搜索模型</button>
          </div>
          <div class="row">
            <input id="hf-repo" style="flex:1" value="Qwen/Qwen3-Embedding-0.6B-GGUF"
                   placeholder="仓库 id，如 Qwen/Qwen3-Embedding-0.6B-GGUF">
            <label class="chip on" id="hf-mirror">hf-mirror 镜像</label>
            <button class="primary" id="hf-browse">浏览文件</button>
          </div>'''
assert old_html in t, "html anchor"
t = t.replace(old_html, new_html, 1)

# 2) JS：替换整个下载段尾部（catalog + handlers + tick），换成真实搜索版
m = re.search(r"/\* ══════════════ 模型下载（LM Studio 式） ══════════════ \*/.*$", t, re.S)
assert m, "dl section not found"
new_tail = '''/* ══════════════ 模型下载（LM Studio 式 · 真实搜索） ══════════════ */
const HF_CATALOG = {   // 离线兜底目录（后端不可用时仍可浏览/模拟下载）
  "Qwen/Qwen3-Embedding-0.6B-GGUF": [
    { file: "Qwen3-Embedding-0.6B-Q8_0.gguf",   mb: 650, q: "Q8_0" },
    { file: "Qwen3-Embedding-0.6B-Q6_K.gguf",   mb: 550, q: "Q6_K" },
    { file: "Qwen3-Embedding-0.6B-Q5_K_M.gguf", mb: 480, q: "Q5_K_M" },
    { file: "Qwen3-Embedding-0.6B-Q4_K_M.gguf", mb: 380, q: "Q4_K_M" },
  ],
  "Qwen/Qwen3-Embedding-4B-GGUF": [
    { file: "Qwen3-Embedding-4B-Q8_0.gguf", mb: 4300, q: "Q8_0" },
    { file: "Qwen3-Embedding-4B-Q4_K_M.gguf", mb: 2500, q: "Q4_K_M" },
  ],
  "Qwen/Qwen3-Embedding-8B-GGUF": [
    { file: "Qwen3-Embedding-8B-Q8_0.gguf", mb: 8300, q: "Q8_0" },
    { file: "Qwen3-Embedding-8B-Q4_K_M.gguf", mb: 4900, q: "Q4_K_M" },
  ],
  "nomic-ai/nomic-embed-text-v1.5-GGUF": [
    { file: "nomic-embed-text-v1.5.Q8_0.gguf", mb: 84, q: "Q8_0" },
    { file: "nomic-embed-text-v1.5.Q4_K_M.gguf", mb: 60, q: "Q4_K_M" },
  ],
};

/* 状态（localStorage 持久化） */
let profiles = store.get("profiles", PRESETS.map(p => ({ ...p })));
let active   = store.get("active", "Agnes 国内");
let embMode  = store.get("embMode", "auto");
let embProfiles = store.get("embProfiles", EMB_PRESETS.map(p => ({ ...p })));
let embActive = store.get("embActive", "LM Studio");
let ggufs    = store.get("ggufs", [{ file: "Qwen3-Embedding-0.6B-Q8_0.gguf", mb: 650 }]);
let ggufUse  = store.get("ggufUse", "Qwen3-Embedding-0.6B-Q8_0.gguf");
let downloads = store.get("downloads", {});
let hfRepo = store.get("hfRepo", "Qwen/Qwen3-Embedding-0.6B-GGUF");
let hfFiles = [];                    // 当前浏览仓库的文件列表
let backendLive = null;              // 本地控制台后端是否在线（8765）

function save() {
  store.set("profiles", profiles); store.set("active", active);
  store.set("embMode", embMode); store.set("embProfiles", embProfiles);
  store.set("embActive", embActive); store.set("ggufs", ggufs);
  store.set("ggufUse", ggufUse); store.set("downloads", downloads);
  store.set("hfRepo", hfRepo);
}
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const $ = id => document.getElementById(id);
const fmtW = n => n >= 10000 ? (n / 1000).toFixed(1) + "k" : String(n);

/* —— 本地后端探测（在线时走真实 HF 数据，离线用内置目录） —— */
async function probeBackend() {
  try {
    const ctl = new AbortController();
    setTimeout(() => ctl.abort(), 1500);
    const r = await fetch("http://127.0.0.1:8765/api/status", { signal: ctl.signal });
    backendLive = r.ok;
  } catch { backendLive = false; }
  return backendLive;
}
async function backendApi(path) {     // 经本地控制台代理 HF（服务端翻墙，无 CORS）
  const r = await fetch("http://127.0.0.1:8765" + path);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}
const quantOf = f => (f.match(/(IQ\\d_\\w+|Q\\d_K_S?|Q\\d_K_M|Q\\d_0|Q\\d|f16|bf16)/i) || [""])[0].toUpperCase();

/* —— 搜索：关键词 → 仓库列表（在线结果 + 离线目录合并） —— */
async function searchModels() {
  const kw = $("hf-kw").value.trim();
  if (!kw) return;
  const box = $("hf-files");
  if (backendLive === null) await probeBackend();
  box.innerHTML = `<div class="dl-row"><span class="pulse-dot"></span><span class="small">搜索中（${backendLive ? "经本地后端 · 在线数据" : "后端离线 · 仅离线目录"}）…</span></div>`;
  let repos = [];
  if (backendLive) {
    try {
      const r = await backendApi(`/api/embed/hf/search?kw=${encodeURIComponent(kw)}&mirror=true`);
      repos = r.repos.map(x => ({ id: x.id, downloads: x.downloads, likes: x.likes, online: true }));
    } catch (e) { /* 落到离线目录 */ }
  }
  const kws = kw.toLowerCase().split(/\\s+/).filter(Boolean);
  for (const repo of Object.keys(HF_CATALOG)) {
    const rl = repo.toLowerCase();
    if (kws.some(w => rl.includes(w)) && !repos.find(x => x.id === repo))
      repos.unshift({ id: repo, downloads: 0, likes: 0, offline: true });
  }
  if (!repos.length) { box.innerHTML = `<span class="empty">没有匹配的仓库（离线目录仅含 Qwen3/nomic 系列；启动控制台后端可搜全网 GGUF）</span>`; return; }
  box.innerHTML = `<div class="muted small" style="margin-bottom:8px">找到 ${repos.length} 个仓库 · 点击查看可下载文件</div>`;
  repos.forEach(rep => {
    const row = document.createElement("div");
    row.className = "dl-row";
    row.style.cursor = "pointer";
    row.innerHTML =
      `<div class="body"><div class="name">${esc(rep.id)}</div>` +
      `<div class="sub">${rep.online ? "🟢 在线" : "📁 离线目录"}${rep.downloads ? ` · 下载量 ${fmtW(rep.downloads)}` : ""}${rep.likes ? ` · ★${rep.likes}` : ""}</div></div>` +
      `<span class="tag use">查看文件</span>`;
    row.addEventListener("click", () => { $("hf-repo").value = rep.id; hfRepo = rep.id; save(); browseRepo(); });
    box.appendChild(row);
  });
}

/* —— 浏览仓库文件：在线优先，离线目录兜底 —— */
async function browseRepo() {
  const repo = hfRepo = $("hf-repo").value.trim() || hfRepo;
  save();
  const box = $("hf-files");
  if (backendLive === null) await probeBackend();
  let files = null, src = "";
  if (backendLive) {
    try {
      const r = await backendApi(`/api/embed/hf/files?repo=${encodeURIComponent(repo)}&mirror=true`);
      files = (r.files || []).map(f => ({ file: f.file, mb: f.size_mb }));
      src = "🟢 在线列表";
    } catch { /* 兜底 */ }
  }
  if (!files && HF_CATALOG[repo]) { files = HF_CATALOG[repo]; src = "📁 离线目录"; }
  if (!files) { box.innerHTML = `<span class="empty">未获取到文件（后端离线且不在离线目录）。启动控制台后端后重试，或从离线目录选择仓库。</span>`; return; }
  box.innerHTML = `<div class="muted small" style="margin-bottom:8px">${esc(repo)} · ${files.length} 个文件 · ${src}</div>`;
  files.forEach(f => {
    const q = quantOf(f.file) || f.q || "";
    const dling = downloads[f.file] && !downloads[f.file].done;
    const doneFile = ggufs.find(g => g.file === f.file);
    const row = document.createElement("div");
    row.className = "dl-row";
    row.innerHTML =
      `<div class="body"><div class="name">${esc(f.file)}</div>` +
      `<div class="sub">${esc(repo)}</div>` +
      `<div class="dl-bar" style="display:${dling ? "block" : "none"}"><div style="width:${dling ? downloads[f.file].pct : 0}%"></div></div>` +
      (dling ? `<div class="dl-info">${downloads[f.file].pct}% · ${downloads[f.file].speed} MB/s</div>` : ``) +
      `</div>` +
      (q ? `<span class="qbadge">${esc(q)}</span>` : ``) +
      `<span class="muted small">${f.mb} MB</span>` +
      (doneFile ? `<span class="tag use">✓ 已下载</span>`
                : `<button class="primary mini" data-dl="${esc(f.file)}" ${dling ? "disabled" : ""}>${dling ? "下载中" : "下载"}</button>`);
    const btn = row.querySelector("[data-dl]");
    if (btn) btn.addEventListener("click", () => startDownload({ file: f.file, mb: f.mb }));
    box.appendChild(row);
  });
  tickDownloads();
}
$("hf-search").addEventListener("click", searchModels);
$("hf-kw").addEventListener("keydown", e => { if (e.key === "Enter") searchModels(); });
$("hf-browse").addEventListener("click", browseRepo);
$("hf-mirror").addEventListener("click", () => $("hf-mirror").classList.toggle("on"));

/* —— 下载队列（演示模拟；真实环境由后端实际落盘） —— */
function startDownload(f) {
  downloads[f.file] = { mb_total: f.mb, mb_done: 0, pct: 0, speed: (2 + Math.random() * 6).toFixed(1), done: false };
  save(); browseRepo(); renderQueue(); renderGgufs();
}
function renderQueue() {
  const act = Object.entries(downloads).filter(([f, d]) => !d.done);
  const q = $("dl-queue");
  q.innerHTML = act.length ? act.map(([f, d]) =>
    `<div class="dl-row"><span class="pulse-dot"></span>` +
    `<div class="body"><div class="name">${esc(f)}</div>` +
    `<div class="dl-bar"><div style="width:${d.pct}%"></div></div></div>` +
    `<span class="dl-info">${d.pct}% · ${d.speed} MB/s</span></div>`).join("")
    : `（无进行中任务）`;
  $("dl-done-hint").textContent = `${ggufs.length} 个`;
  $("cnt-dl").textContent = ggufs.length;
}
function tickDownloads() {
  let any = false;
  for (const [file, d] of Object.entries(downloads)) {
    if (d.done) continue;
    any = true;
    d.mb_done = Math.min(d.mb_total, d.mb_done + Number(d.speed) * 0.6);
    d.pct = Math.round(d.mb_done / d.mb_total * 100);
    if (d.mb_done >= d.mb_total) {
      d.done = true;
      if (!ggufs.find(g => g.file === file)) ggufs.push({ file, mb: d.mb_total });
    }
  }
  save();
  if ($("panel-dl").classList.contains("active")) { renderQueue(); if (any && hfFiles.length) browseRepo(); }
  if (any) setTimeout(tickDownloads, 600);
}

/* ══════════════ 生成供应商 ══════════════ */
let profiles = store.get("profiles", PRESETS.map(p => ({ ...p })));
let active   = store.get("active", "Agnes 国内");
function renderProv() {
  const q = ($("prov-q").value || "").toLowerCase();
  const tag = $("prov-tag").value;
  const list = profiles.filter(p =>
    (!tag || (p.tag || "自定义") === tag || (tag === "自定义" && p.custom)) &&
    (!q || p.name.toLowerCase().includes(q) || p.model.toLowerCase().includes(q) || p.url.toLowerCase().includes(q)));
  $("prov-total").textContent = `共 ${profiles.length} 家 · 显示 ${list.length}`;
  $("cnt-prov").textContent = profiles.length;
  const box = $("prov-list");
  box.innerHTML = "";
  list.forEach(p => {
    const act = p.name === active;
    const row = document.createElement("div");
    row.className = "prof" + (act ? " active" : "");
    row.innerHTML =
      `<div class="body"><div class="name">${esc(p.name)}` +
      (p.free ? ` <span class="tag free">免费档</span>` : ``) +
      (p.local ? ` <span class="tag local">本地</span>` : ``) +
      (p.key ? `<span class="tag key" title="档案自带 key">🔑</span>` : ``) +
      `</div><div class="sub">${esc(p.url)} · ${esc(p.model)}</div></div>` +
      `<span class="tag">${esc(p.tag || "")}</span>` +
      (act ? `<span class="tag use">● 使用中</span>` : ``) +
      `<div class="ops"><button class="mini" data-edit="${esc(p.name)}">✎</button>` +
      `<button class="mini danger" data-del="${esc(p.name)}">🗑</button></div>`;
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-edit]")) { fillForm(p); return; }
      if (e.target.closest("[data-del]")) {
        if (!confirm(`删除档案「${p.name}」？`)) return;
        profiles = profiles.filter(x => x.name !== p.name);
        if (active === p.name) active = profiles[0].name;
        save(); renderProv(); return;
      }
      active = p.name; save(); renderProv();
    });
    box.appendChild(row);
  });
}
function fillForm(p) {
  $("np-title").textContent = "✎ 编辑档案 · " + p.name;
  $("np-name").value = p.name; $("np-url").value = p.url;
  $("np-model").value = p.model; $("np-key").value = p.key || "";
  $("np-tag").value = p.tag || ""; $("np-name").focus();
}
$("prov-q").addEventListener("input", renderProv);
$("prov-tag").addEventListener("change", renderProv);
$("np-eye").addEventListener("click", () => {
  const k = $("np-key"); k.type = k.type === "password" ? "text" : "password";
});
$("np-reset").addEventListener("click", () => {
  ["np-name", "np-url", "np-model", "np-key", "np-tag"].forEach(id => $(id).value = "");
  $("np-title").textContent = "＋ 新增 / 修改档案";
});
$("np-save").addEventListener("click", () => {
  const name = $("np-name").value.trim(), url = $("np-url").value.trim();
  const model = $("np-model").value.trim(), key = $("np-key").value.trim();
  const tag = $("np-tag").value.trim() || "自定义";
  if (!name || !url) { $("np-msg").className = "msg err"; $("np-msg").textContent = "名称与 URL 必填"; return; }
  const i = profiles.findIndex(p => p.name === name);
  const prof = { name, url, model, tag: i >= 0 ? (profiles[i].tag || tag) : tag,
                 custom: true, ...(key ? { key } : {}) };
  if (i >= 0) profiles[i] = prof; else profiles.push(prof);
  active = name; save(); renderProv();
  $("np-msg").className = "msg ok"; $("np-msg").textContent = `✓ 已保存并启用「${name}」`;
  setTimeout(() => $("np-msg").textContent = "", 3000);
});
$("prov-test").addEventListener("click", () => {
  const el = $("prov-test-msg");
  el.className = "msg muted"; let ms = 0;
  const t = setInterval(() => { ms += 80; el.textContent = `测试中 ${ms}ms…`; }, 80);
  setTimeout(() => {
    clearInterval(t);
    const ok = Math.random() > 0.25 || active.includes("国内");
    el.className = "msg " + (ok ? "ok" : "err");
    el.textContent = ok ? `✓ 连通（${300 + Math.floor(Math.random() * 500)}ms）` : "✗ 连接失败（检查 key/网络）";
  }, 900);
});

/* ══════════════ 检索 Embedding ══════════════ */
let embProfiles = store.get("embProfiles", EMB_PRESETS.map(p => ({ ...p })));
let embActive = store.get("embActive", "LM Studio");
let embMode  = store.get("embMode", "auto");
function renderEmb() {
  document.querySelectorAll("#emb-mode .chip").forEach(c =>
    c.classList.toggle("on", c.dataset.m === embMode));
  const list = $("emb-list");
  list.innerHTML = "";
  embProfiles.forEach(p => {
    const act = p.name === embActive;
    const row = document.createElement("div");
    row.className = "prof" + (act ? " active" : "");
    row.innerHTML =
      `<div class="body"><div class="name">${esc(p.name)}${p.key ? `<span class="tag key">🔑</span>` : ``}</div>` +
      `<div class="sub">${esc(p.url)} · ${esc(p.model)}</div></div>` +
      (p.local ? `<span class="tag local">本地</span>` : ``) +
      (act ? `<span class="tag use">● 使用中</span>` : ``) +
      `<div class="ops"><button class="mini" data-edit="${esc(p.name)}">✎</button>` +
      `<button class="mini" data-del="${esc(p.name)}">🗑</button></div>`;
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-edit]")) { $("ep-name").value = p.name; $("ep-url").value = p.url;
        $("ep-model").value = p.model; $("ep-key").value = p.key || ""; return; }
      if (e.target.closest("[data-del]")) { if (!confirm(`删除端点「${p.name}」？`)) return;
        embProfiles = embProfiles.filter(x => x.name !== p.name);
        if (embActive === p.name) embActive = embProfiles[0].name;
        save(); renderEmb(); return; }
      embActive = p.name; save(); renderEmb();
    });
    list.appendChild(row);
  });
  $("llama-state").innerHTML = `<span style="color:var(--green)">✓ 就绪</span>`;
  $("llama-info").innerHTML =
    `<div class="row"><span class="muted" style="min-width:64px">服务端</span>` +
    `<span class="mono small">llama-server.exe（内置，按需拉起）</span></div>` +
    `<div class="row"><span class="muted" style="min-width:64px">当前模型</span>` +
    `<span class="mono small">${esc(ggufUse)}</span></div>`;
  renderGgufs();
}
document.querySelectorAll("#emb-mode .chip").forEach(c => c.addEventListener("click", () => {
  embMode = c.dataset.m; save(); renderEmb();
}));
document.querySelectorAll("[data-epq]").forEach(b => b.addEventListener("click", () => {
  const p = embProfiles.find(x => x.name === b.dataset.epq);
  if (p) { $("ep-name").value = p.name; $("ep-url").value = p.url;
           $("ep-model").value = p.model; $("ep-key").value = p.key || ""; }
}));
$("ep-save").addEventListener("click", () => {
  const name = $("ep-name").value.trim(), url = $("ep-url").value.trim();
  if (!name || !url) { alert("名称与 URL 必填"); return; }
  const key = $("ep-key").value.trim();
  const i = embProfiles.findIndex(x => x.name === name);
  const prof = { name, url, model: $("ep-model").value.trim(),
                 local: url.includes("127.0.0.1") || url.includes("localhost"), ...(key ? { key } : {}) };
  if (i >= 0) embProfiles[i] = prof; else embProfiles.push(prof);
  embActive = name; save(); renderEmb();
});
function renderGgufs() {
  const box = $("gguf-list");
  box.innerHTML = "";
  ggufs.forEach(g => {
    const act = g.file === ggufUse;
    const row = document.createElement("div");
    row.className = "prof" + (act ? " active" : "");
    row.innerHTML =
      `<div class="body"><div class="name">${esc(g.file)}</div></div>` +
      `<span class="p-tag">${g.mb} MB</span>` +
      (act ? `<span class="tag use">● 使用中</span>` : ``) +
      `<div class="ops"><button class="mini danger" data-del="${esc(g.file)}">🗑</button></div>`;
    row.addEventListener("click", (e) => {
      if (e.target.closest("[data-del]")) {
        if (!confirm(`删除 ${g.file}？`)) return;
        ggufs = ggufs.filter(x => x.file !== g.file);
        if (ggufUse === g.file && ggufs.length) ggufUse = ggufs[0].file;
        save(); renderEmb(); return;
      }
      ggufUse = g.file; save(); renderEmb();
    });
    box.appendChild(row);
  });
}

/* ══════════════ 启动 ══════════════ */
(async () => {
  await probeBackend();
  renderProv(); renderEmb(); renderQueue();
  $("head-info").textContent = backendLive
    ? "已连接本地控制台 · 模型数据实时获取"
    : "离线模式 · 启动控制台后端可获取在线模型列表";
})();
'''
t = t[:m.start()] + new_tail
p.write_text(t, encoding="utf-8")
print("demo dl search OK")
