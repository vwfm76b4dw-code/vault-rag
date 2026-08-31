# -*- coding: utf-8 -*-
"""demo 最终重建：干净头部 + 完整尾部，一次拼装。"""
from pathlib import Path
import re

p = Path("docs/model_manager_demo.html")
t = p.read_text(encoding="utf-8")

# 1) HTML 头
cut = t.index("<script>")
html_head = t[:cut + len("<script>")]

# 2) 完整新尾部（状态/搜索/下载/供应商/检索/启动 都在里面）
m = re.search(r"let profiles = store\.get\(\"profiles\"", t)
assert m, "tail state not found"
tail = t[m.start():]

# 3) 预设库（各一份）
presets = re.search(r"const PRESETS = \[.*?\n\];", t, re.S)
emb = re.search(r"const EMB_PRESETS = \[.*?\n\];", t, re.S)
assert presets and emb, "presets missing"

header = '''/* ══════════════ ADAPTER（真实环境替换此区即可） ══════════════ */
const DEMO = true;
const store = {
  get(k, d) { try { const v = localStorage.getItem("vr_" + k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { localStorage.setItem("vr_" + k, JSON.stringify(v)); },
};
async function API(path, params) {
  if (!DEMO) return fetch(path, params);
  await new Promise(r => setTimeout(r, 120));
  return { demo: true };
}
const esc = s => String(s ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
const $ = id => document.getElementById(id);
const fmtW = n => n >= 10000 ? (n / 1000).toFixed(1) + "k" : String(n);

/* ══════════════ 导航 ══════════════ */
const TITLES = { prov: "生成供应商", emb: "检索 Embedding", dl: "模型下载" };
document.querySelectorAll(".nav-item").forEach(b =>
  b.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(x => x.classList.remove("active"));
    document.querySelectorAll(".panel").forEach(x => x.classList.remove("active"));
    b.classList.add("active");
    $("panel-" + b.dataset.nav).classList.add("active");
    $("page-title").textContent = TITLES[b.dataset.nav];
    if (b.dataset.nav === "prov") renderProv();
    if (b.dataset.nav === "emb") renderEmb();
    if (b.dataset.nav === "dl") { $("hf-repo").value = hfRepo; renderDlPage(); }
  }));

/* ══════════════ 生成供应商预设库 ══════════════ */
'''
emb_header = '''

/* ══════════════ Embedding 端点预设 ══════════════ */
'''
script = (header + presets.group(0) + emb_header + emb.group(0)
          + "\n\n" + tail)
out = html_head + "\n" + script + "\n</script>\n</body>\n</html>\n"
p.write_text(out, encoding="utf-8")

# 自检：不允许重复声明
js = out[out.index("<script>") + 8:]
for name in ["let profiles", "let active ", "let ggufs ", "let embProfiles",
             "const PRESETS", "const EMB_PRESETS", "const esc ", "const $ "]:
    n = js.count(name)
    assert n == 1, f"{name} 出现 {n} 次"
print("demo rebuilt clean,", len(out.splitlines()), "lines")
