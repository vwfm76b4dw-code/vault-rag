# -*- coding: utf-8 -*-
"""一次性补丁：四大分区导航 + 多仓库 + 批量上传 + MCP&状态（跑完即删）。"""
from pathlib import Path

# ---- CSS：dropzone + 追加组件 ----
pc = Path("webui_assets/style.css")
c = pc.read_text(encoding="utf-8")
c += """
/* ---------- 批量上传拖拽区 ---------- */
.dropzone { border: 2px dashed var(--line2); border-radius: 10px; padding: 22px;
  text-align: center; color: var(--muted); transition: all .2s; cursor: pointer; }
.dropzone:hover, .dropzone.drag { border-color: var(--green-line); background: var(--green-dim); color: var(--fg); }
.dropzone p { margin: 4px 0; }
"""
pc.write_text(c, encoding="utf-8")

# ---- app.js ----
p = Path("webui_assets/app.js")
t = p.read_text(encoding="utf-8")

# 1) TITLES 扩充
old_t = 'const TITLES = { chat: "问答", board: "看板", repo: "仓库管理", index: "索引与范围",\n                 "models-gen": "生成供应商", "models-emb": "检索 Embedding", settings: "设置" };'
new_t = 'const TITLES = { chat: "问答（检索）", board: "看板", ops: "索引 · 范围 · 上传",\n                 repos: "仓库管理（多 RAG）", index: "索引与范围",\n                 "models-gen": "生成供应商", "models-emb": "检索 Embedding",\n                 mcp: "MCP & 状态", settings: "高级设置" };'
assert old_t in t, "TITLES anchor"
t = t.replace(old_t, new_t, 1)

# 2) nav() 分发重构
old_nav = '''  $("panel-" + name).classList.add("active");
  $("page-title").textContent = TITLES[name] || name;
  if (name === "board") loadBoard();
  if (name === "repo") loadRepo();
  if (name === "index") loadManage();
  if (name === "models-gen") renderProviders().catch(() => {});
  if (name === "models-emb") renderEmbed().catch(() => {});
  if (name === "settings") { loadPrefs().catch(() => {}); loadSettingsInfo().catch(() => {}); }
  closeNavOnSmall();'''
new_nav = '''  $("panel-" + name).classList.add("active");
  $("page-title").textContent = TITLES[name] || name;
  const loaders = {
    board: loadBoard, repo: loadRepo, index: loadManage, ops: loadManage,
    "models-gen": () => renderProviders(),
    "models-emb": () => renderEmbed(),
    settings: async () => { await loadPrefs(); await loadSettingsInfo(); },
    mcp: loadMcpStatus, repos: loadRepos,
  };
  if (loaders[name]) Promise.resolve(loaders[name]()).catch(e => console.error(name, e));
  closeNavOnSmall();'''
assert old_nav in t, "nav anchor"
t = t.replace(old_nav, new_nav, 1)

# 3) 仓库页入口改为多仓库页
t = t.replace('if (btn.dataset.tab === "repo") loadRepo();',
              'if (btn.dataset.nav === "repos") loadRepos();')  # 兼容旧选择器（无副作用）

# 4) 追加：多仓库 + 批量上传 + MCP&状态 逻辑
t += '''
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
        if (!confirm(`切换到仓库「${r0.name}」？\\n（问答/看板/仓库页立即跟随；独立 MCP 进程重启后跟随）`)) return;
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
  const fd = new FormData();
  let n = 0;
  for (const f of fileList) { fd.append("files", f); n++; }
  if (!n) return;
  $("upload-result").className = "msg muted";
  $("upload-result").textContent = `上传中（${n} 个文件）…`;
  try {
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || r.statusText);
    $("upload-result").className = "msg ok";
    $("upload-result").textContent = `✓ ${d.saved.length} 个文件已入库并加入范围` +
      (d.skipped.length ? `（跳过: ${d.skipped.join(", ")}）` : "");
    $("upload-actions").style.display = "flex";
    $("upload-batchdir").textContent = d.batch_dir;
    $("btn-upload-index").onclick = async () => {
      $("upload-actions").style.display = "none";
      await post("/api/index/refresh");
      nav("ops"); pollIndex();
    };
  } catch (e) {
    $("upload-result").className = "msg err";
    $("upload-result").textContent = "✗ " + e.message;
  }
}

/* ================= MCP & 状态 ================= */
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
  if (!confirm("把 vault-rag MCP 注册进 Claude Code（~/.claude.json，自动备份）？\\n注册后需重启 Claude Code 生效。")) return;
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
'''
p.write_text(t, encoding="utf-8")
print("app.js IA2 OK")
