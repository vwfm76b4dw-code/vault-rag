# -*- coding: utf-8 -*-
"""project_tree.py — 项目/主题知识树生成器（只读，产物写 data/trees/）

用法：
    python project_tree.py all            # 全库聚类→树输出 data/project_trees.md + mermaid
    python project_tree.py <关键词>        # 单簇详图（如 "SDD" / "tdd"）
"""
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vault_rag.freshness import VAULT, extract_signals, rank_cluster, cluster_kind
from vault_rag.config import DATA_DIR
from vault_rag import scope as scopes

OUT_MD = DATA_DIR / "project_trees.md"


def build_clusters():
    clusters = defaultdict(list)
    for rel, p in scopes.collect_files():        # 与索引器同一声明范围
        try:
            f = extract_signals(p, rel)
        except Exception:
            continue
        clusters[f.cluster_key].append(f)
    return {k: v for k, v in clusters.items() if len(v) >= 2}   # ≥2 才算簇


def render(clusters):
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# vault-rag 项目知识树（{now}）", "",
             "> 自动聚类规则：标题去日期/序号归一化。★=权威版本 ▽=沉底(历史/残骸) ⚠=待人工合并", ""]
    multi = 0
    for key, members in sorted(clusters.items(), key=lambda kv: -len(kv[1])):
        w, stale = rank_cluster(members)
        kind = cluster_kind(members)
        n_fresh = len(members) - len(stale)
        tag = {"temporal_series": " 📅时序流·全保留", "version": " 版本簇", "mixed": " ⚠待人工"}[kind]
        mark = tag if kind != "version" else (" ⚠多活版本待合并" if n_fresh > 1 else "")
        lines.append(f"\n## {key}{mark}")
        for m in sorted(members, key=lambda x: (x.rel_path != w, -(x.size if x.rel_path == w else x.size * 0.999))):
            sym = "★" if m.rel_path == w else ("▽" if m.is_stale_source else "•")
            d = m.best_date or "?"
            lines.append(f"- {sym} `{m.rel_path}` ({m.size:,}字, {d})")
        if n_fresh > 1:
            lines.append(f"- 💡 活跃版本仍有 {n_fresh} 个，建议合并或显式声明 superseded_by")
        multi += 1
    head = [f"共 {multi} 个多文件簇\n"]
    OUT_MD.write_text("\n".join(head + lines), encoding="utf-8")
    print(f"[tree] {multi} 簇已写入 {OUT_MD}")
    return multi


def mermaid_sample(clusters, top=5):
    """给最大的几个簇出 mermaid 谱系图（嵌进 md 尾部供 Obsidian 渲染）"""
    out = ["", "```mermaid", "graph LR"]
    for i, (key, members) in enumerate(sorted(clusters.items(), key=lambda kv: -len(kv[1]))[:top]):
        w, stale = rank_cluster(members)
        out.append(f"  subgraph C{i}[{key[:16]}]")
        for j, m in enumerate(members):
            nid = f"c{i}_{j}"
            tag = "★" if m.rel_path == w else ("▽" if m.is_stale_source else "")
            out.append(f'    {nid}["{Path(m.rel_path).name[:24]}{tag}"]')
        wi = next(j for j, m in enumerate(members) if m.rel_path == w) if w else None
        if wi is not None:
            for j, m in enumerate(members):
                if j != wi and m.is_stale_source:
                    out.append(f"    c{i}_{j} -.被取代.-> c{i}_{wi}")
        out.append("  end")
    out += ["```", ""]
    with open(OUT_MD, "a", encoding="utf-8") as f:
        f.write("\n".join(out))
    print("[tree] mermaid 谱系图已追加")


if __name__ == "__main__":
    clusters = build_clusters()
    arg = sys.argv[1] if len(sys.argv) > 1 else "all"
    if arg != "all":
        key = arg.lower()
        hit = {k: v for k, v in clusters.items() if key in k}
        for k, ms in hit.items():
            w, s = rank_cluster(ms)
            print(f"\n[{k}]")
            for m in ms:
                sym = "★" if m.rel_path == w else ("▽" if m.is_stale_source else "•")
                print(f"  {sym} {m.rel_path} ({m.size:,}字)")
    else:
        render(clusters)
        mermaid_sample(clusters)
