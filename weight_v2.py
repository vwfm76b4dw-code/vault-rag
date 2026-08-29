# -*- coding: utf-8 -*-
"""weight_v2.py — 权重机制 v2（引用数基础 + 项目继承×0.5 + AI 多角度评价）

公式：
  base      = min(in_degree × 4, 25)                      # 延续旧 centrality，引用文章数驱动
  inherit   = max(0, 重要度(所属项目) × 0.5)               # 仅 vault 根级散落文件适用
              重要度 = 该项目目录内笔记的 base 中位数
  ai_score  = (结构/信息密度/时效价值/独特性 四维均分 0~25)  # agnes2.5-flash 或 claude -p
  computed  = min(100, base + inherit + ai_bonus)          # ai_bonus = ai_score×(1 if 评过 else 0)
存储：data/weights.db（git 版本化），manual_weight(frontmatter) 仍永远优先。
"""
import json, os, re, sqlite3, statistics, subprocess, sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR, VAULT, FTS_DB
import scope as scopes

WDB = DATA_DIR / "weights.db"

DIMENSIONS = ("structure", "density", "timeliness", "uniqueness")


def init(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS weights(
            rel_path TEXT PRIMARY KEY,
            in_degree INTEGER, base INTEGER, inherit REAL,
            ai_structure INTEGER, ai_density INTEGER, ai_timeliness INTEGER, ai_uniqueness INTEGER,
            ai_total REAL, computed INTEGER, updated_at TEXT);
    """)


def compute_graph():
    """in_degree 双通道：wikilink + complements/supersedes 关系边。"""
    deg = defaultdict(int)
    def _norm_target(t):
        # target 可能是 "SDD-规格驱动开发深度研究" / "知识/原理/X.md" / "[[X|别名]]"
        t = re.sub(r"^\[\[|\]\]$", "", str(t))
        t = t.split("|")[0].strip()
        return Path(t).name if "/" in t or t.endswith(".md") else t + ".md"
    try:
        vc = sqlite3.connect(f"file:{FTS_DB}?mode=ro", uri=True)
        tables = {r[0] for r in vc.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        if "notes_links" in tables:
            for s, t in vc.execute("SELECT source, target FROM notes_links"):
                deg[_norm_target(t)] += 1
        vc.close()
    except Exception as e:
        print(f"[deg] link table err: {str(e)[:50]}")
    rdb = DATA_DIR / "relations.db"
    if rdb.exists():
        rc = sqlite3.connect(f"file:{rdb}?mode=ro", uri=True)
        for dst in rc.execute("SELECT dst FROM edges WHERE kind IN ('complements','supersedes')"):
            deg[dst[0].split("/")[-1]] += 1
        rc.close()
    return deg


def project_importance(files):
    """根级散落文件的继承分来源：各目录内笔记 base 中位数 ×0.5。"""
    deg = compute_graph()
    by_dir_bases = defaultdict(list)
    dir_of = {}
    for rel, p in files.items():
        top = rel.split("/")[0] if "/" in rel else None
        d = deg.get(Path(rel).name, 0)
        b = min(d * 4, 25)
        if top and top not in {"知识", "研究", "项目", "笔记", "记忆"}:
            by_dir_bases[top].append(b)
        dir_of[rel] = top
    proj_w = {k: round(min(statistics.median(v) * 0.5, 12.5), 2)
              for k, v in by_dir_bases.items() if len(v) >= 3}
    inherit = {}
    for rel, top in dir_of.items():
        if top is None:                       # vault 根级散文件才吃继承
            # 从正文/frontmatter 猜项目归属词表太脆——先按文件名匹配目录名
            stem = Path(rel).stem.lower()
            best = max((w for k, w in proj_w.items() if k.lower() in stem), default=None)
            if best: inherit[rel] = best
    return inherit, proj_w


def ai_eval_batch(texts_labels, backend="claude"):
    """多角度评价：每批 ≤20 篇摘要卡 → 一次调用输出 JSON。失败返回 {}。"""
    prompt = (
        "你是知识库评分器。对下列每篇笔记摘要按四个维度打分(0-25整数)："
        "structure结构清晰度 density信息密度 timeliness时效价值 uniqueness独特性。\n"
        "严格输出 JSON 数组，元素形如 {\"id\":序号,\"scores\":[s,d,t,u]}，不要任何其他文字。\n\n"
        + "\n".join(f"[{i}] {lab}" for i, lab in enumerate(texts_labels)))
    try:
        if backend == "claude":
            import shutil as _sh
            # wrapper 路径可经环境变量覆盖；默认定位 npm 全局安装的 claude-code
            wrapper = Path(os.environ.get(
                "CLAUDE_WRAPPER",
                str(Path(os.environ.get("APPDATA", "")) / "npm" / "node_modules"
                    / "@anthropic-ai" / "claude-code" / "cli-wrapper.cjs")))
            node = _sh.which("node") or "node"
            if not wrapper.exists():
                raise RuntimeError("claude CLI wrapper 不存在")
            env = {**os.environ, "CLAUDE_CODE_ENTRYPOINT": "weight-v2"}   # 标记来源，防钩子递归
            r = subprocess.run([node, str(wrapper), "-p", prompt],
                               capture_output=True, text=True, timeout=420,
                               encoding="utf-8", env=env)
            out = r.stdout
        else:  # agnes openai-compatible
            import requests
            key = os.environ.get("AGNES_KEY", "")
            rj = requests.post("https://api.agnes-ai.cn/v1/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "agnes-2.5-flash",
                      "messages": [{"role": "user", "content": prompt}],
                      "temperature": 0}, timeout=120)
            out = rj.json()["choices"][0]["message"]["content"]
        m = re.search(r"\[.*\]", out, re.S)
        if not m:
            return {}
        parsed = {}
        for e in json.loads(m.group(0)):
            sc = e.get("scores") or []
            if len(sc) >= 4:      # 防御：截断到四维并夹紧 0~25，LLM 偶发越界
                parsed[int(e["id"])] = [max(0, min(25, int(s))) for s in sc[:4]]
        return parsed
    except Exception as e:
        print(f"[ai] backend={backend} failed: {str(e)[:60]}", flush=True)
        return {}


def summarize_for_eval(p: Path, limit=700):
    t = p.read_text(encoding="utf-8", errors="replace")
    t = re.sub(r"^---.*?---", "", t[:limit*3], count=1, flags=re.S)   # 去 frontmatter
    return " ".join(t.split())[:limit]


def run(ai_backend="claude", sample=None, refresh_all=False):
    files = dict(scopes.collect_files())
    con = sqlite3.connect(WDB); init(con)
    existing = {r[0]: r for r in con.execute("SELECT * FROM weights")}
    deg = compute_graph()
    inherit, proj_w = project_importance(files)
    todo = [(rel, p) for rel, p in files.items()
            if refresh_all or rel not in existing]
    if sample: todo = todo[:sample]
    print(f"[w2] 重算 {len(todo)} 篇 | ai后端={ai_backend} | 项目继承映射: {proj_w}")
    for bi in range(0, len(todo), 20):
        chunk = todo[bi:bi+20]
        scores = ai_eval_batch([f"{Path(r).name}: {summarize_for_eval(p, 300)}"
                                for r, p in chunk], ai_backend) if ai_backend else {}
        rows = []
        for j, (rel, p) in enumerate(chunk):
            d = deg.get(Path(rel).name, 0)
            base = min(d * 4, 25)
            inh = inherit.get(rel, 0.0)
            sc = scores.get(j)
            old = existing.get(rel)
            if not sc and old and old[4] is not None:     # 保留历史 AI 分
                sc = [old[4], old[5], old[6], old[7]]
            ai_t = sum(sc) if sc else None
            comp = int(min(100, base + inh + (ai_t * 0.5 if ai_t else 0)))
            rows.append((rel, d, base, inh, *(sc or [None]*4),
                         ai_t, comp, datetime.now(timezone.utc).isoformat(timespec="seconds")))
        con.executemany("INSERT OR REPLACE INTO weights VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.commit()
        print(f"\r[w2] {min(bi+20,len(todo))}/{len(todo)}", end="", flush=True)
    print()
    hi = con.execute("SELECT rel_path, computed FROM weights ORDER BY computed DESC LIMIT 8").fetchall()
    for r, c in hi: print(f"  {c:>3}  {r[:60]}")
    con.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    backend = next((a.split("=")[1] for a in args if a.startswith("--ai=")), "claude")
    if "--off" in args: backend = None
    samp = next((int(a.split("=")[1]) for a in args if a.startswith("--sample=")), None)
    run(ai_backend=backend, sample=samp, refresh_all="--all" in args)
