# -*- coding: utf-8 -*-
"""relations.py — 文档关系层：把 vault 从「文件集合」升格为「知识图谱」。

四种边（有向，带类型与置信度）：
  supersedes   A 取代 B          ← freshness S1/S2 裁决（★→▽）
  sibling      同簇共存(时序流)   ← cluster_kind=temporal_series，按日期成链
  complements  跨簇主题互补       ← 向量 sim≥0.75 且不同簇 或 共享标签/正文互提
  references   显式 wikilink     ← notes_links 表现成数据

产物：data/relations.db (edges 表)，供 RAG-Obsidian MCP 的 get_note_relations 用。
"""
import re, sqlite3, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from config import DATA_DIR
from freshness import VAULT, extract_signals, rank_cluster, cluster_of, cluster_kind
import scope as scopes

DB = DATA_DIR / "relations.db"

TAG_RE = re.compile(r"^tags:\s*\[([^\]]*)\]", re.M)


def init(con):
    con.executescript("""
        CREATE TABLE IF NOT EXISTS edges(
            src TEXT, dst TEXT, kind TEXT, conf REAL, why TEXT,
            PRIMARY KEY(src, dst, kind));
        CREATE INDEX IF NOT EXISTS idx_e_src ON edges(src);
        CREATE INDEX IF NOT EXISTS idx_e_dst ON edges(dst);
    """)


def build_edges():
    con = sqlite3.connect(DB); init(con)
    con.execute("DELETE FROM edges")
    files = dict(scopes.collect_files())
    members = {}
    for rel, p in files.items():
        try:
            members[rel] = extract_signals(p, rel)
        except Exception:
            continue
    # ① supersedes + ② sibling（按簇）
    clusters = {}
    for rel, m in members.items():
        clusters.setdefault(m.cluster_key, []).append(m)
    for key, ms in clusters.items():
        if len(ms) < 2: continue
        kind = cluster_kind(ms)
        w, stale = rank_cluster(ms)
        if kind == "version":
            for s in stale:
                con.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)",
                            (w, s, "supersedes", 0.95, "freshness S1/S2 裁决"))
        elif kind == "temporal_series":
            dated = sorted((m for m in ms if m.best_date), key=lambda m: m.best_date)
            for a, b in zip(dated, dated[1:]):
                con.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)",
                            (a.rel_path, b.rel_path, "sibling_next", 0.9, f"时序流 {a.best_date}→{b.best_date}"))
    # ④ references（读现成 wikilink 图）
    vdb = Path.home() / ".claude/mcp_servers/obsidian-search/vault_new.db"
    if vdb.exists():
        vc = sqlite3.connect(f"file:{vdb}?mode=ro", uri=True)
        by_stem = {Path(r).stem: r for r in members}
        for src, tgt in vc.execute("SELECT source, target FROM notes_links"):
            tnorm = tgt.split("/")[-1].replace(".md", "")
            dst = by_stem.get(tnorm)
            if dst and dst != src and src in members:
                con.execute("INSERT OR IGNORE INTO edges VALUES(?,?,?,?,?)",
                            (src, dst, "references", 1.0, "wikilink"))
        vc.close()
    con.commit()
    n = {k: c for k, c in con.execute("SELECT kind, COUNT(*) FROM edges GROUP BY kind")}
    con.close()
    return n


def complement_scan(sample_limit=None):
    """③ complements：跨簇高相似对。需模型，单独跑批（较慢）。"""
    import numpy as np
    from search import embed_query, search as _s   # noqa
    con = sqlite3.connect(DB); init(con)
    # 每篇取首块向量做代表 → 两两比较成本高；改用 top-k 近邻法：
    # 对每个"簇代表块"检索相似内容，过滤同簇，sim≥0.75 记 complements
    sc = sqlite3.connect(str(DATA_DIR / "qwen_rag.db"))
    reps = {}
    for cid, rp, txt in sc.execute(
            "SELECT chunk_id, rel_path, text FROM chunks WHERE seq=0 AND rel_path NOT LIKE '%.codex%'"):
        reps[rp] = (cid, txt)
    import indexer_qwen as iq
    items = list(reps.items())
    if sample_limit: items = items[:sample_limit]
    added = 0
    keys = [k for k, _ in items]
    # 批量编码代表块
    BATCH = 16
    embs = []
    for i in range(0, len(keys), BATCH):
        texts = [reps[k][1][:600] for k in keys[i:i+BATCH]]
        embs.append(iq.embed_batch(texts))
        print(f"\rcomplement encode {min(i+BATCH,len(keys))}/{len(keys)}", end="", flush=True)
    E = np.vstack(embs); E /= np.linalg.norm(E, axis=1, keepdims=True)
    S = E @ E.T
    ck = {k: cluster_of(k) for k in keys}
    for i, ka in enumerate(keys):
        for j in np.argsort(-S[i])[:8]:
            if j <= i: continue
            kb = keys[int(j)]
            if S[i, int(j)] < 0.75: break
            if ck[ka] == ck[kb]: continue          # 同簇已处理
            con.execute("INSERT OR REPLACE INTO edges VALUES(?,?,?,?,?)",
                        (ka, kb, "complements", float(S[i, int(j)]), "跨簇向量相似"))
            added += 1
    con.commit(); con.close()
    return added


def get_relations(rel_path: str, depth: int = 1) -> dict:
    """查询一篇笔记的全部关系（MCP 工具核心）。"""
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    out = {"outgoing": [], "incoming": []}
    for dst, kind, conf, why in con.execute(
            "SELECT dst,kind,conf,why FROM edges WHERE src=? ORDER BY conf DESC", (rel_path,)):
        out["outgoing"].append({"to": dst, "kind": kind, "conf": round(conf, 3), "why": why})
    for src, kind, conf, why in con.execute(
            "SELECT src,kind,conf,why FROM edges WHERE dst=? ORDER BY conf DESC", (rel_path,)):
        out["incoming"].append({"from": src, "kind": kind, "conf": round(conf, 3), "why": why})
    con.close()
    return out


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "build"
    if mode == "build":
        print("fast edges:", build_edges())
    elif mode == "complement":
        lim = int(sys.argv[2]) if len(sys.argv) > 2 else None
        print("\ncomplements added:", complement_scan(lim))
    elif mode == "show":
        import json; print(json.dumps(get_relations(sys.argv[2]), ensure_ascii=False, indent=1))
