# -*- coding: utf-8 -*-
"""freshness.py — 文件时效性信号引擎（只读分析，不碰 vault）

五级信号链（可信度降序）：
  S1 显式声明   frontmatter updated/superseded_by + 正文「历史版本」标记 → 权威
  S2 数据量证据 同簇内体积断层(≥5x) → 小者判残骸/摘要          （08-27实测）
  S3 嵌入时间   文件名日期 > frontmatter.date > 正文最新日期    （mtime不可信，08-18批量触碰教训）
  S4 git 基线   .ragfiles manifest 的 mtime diff → 真实编辑史
  S5 向量近重复 sim≥0.92 → 合并候选交人工裁
"""
import re
from dataclasses import dataclass, field
from datetime import datetime
import os
import os
import os
from pathlib import Path

VAULT = Path(os.environ.get("VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault")))
DATE_IN_NAME = re.compile(r"(20\d{2})[-—]?(\d{2})?(?:[-—]?(\d{2}))?")
FM_KV = re.compile(r"^(updated|date|superseded_by|replaced_by)\s*:\s*(.+)$", re.M)
HIST_MARK = re.compile(r"历史版本|superseded|已被替代|旧版存档")


@dataclass
class Freshness:
    rel_path: str
    size: int
    embedded_date: str | None = None     # S3 归一后的"内容日期"
    declared_updated: str | None = None  # S1 frontmatter updated
    superseded_by: str | None = None     # S1 显式指针
    has_history_mark: bool = False       # S1 正文声明
    is_stale_source: bool = False        # S2 被同簇大文件压制
    cluster_key: str = ""                # 项目/主题聚类键
    signals: list = field(default_factory=list)

    @property
    def best_date(self):
        return self.declared_updated or self.embedded_date

    @property
    def authority_rank(self):
        """排序权重：越新越权威；显式历史版本直接沉底。"""
        if self.has_history_mark or self.superseded_by or self.is_stale_source:
            return (0, "")
        return (1, self.best_date or "0000")


def extract_signals(path: Path, rel: str) -> Freshness:
    raw = path.read_text(encoding="utf-8", errors="replace")
    fm = dict(FM_KV.findall(raw[:800])) if raw.startswith("---") else {}
    head = raw[:600]
    # S3 嵌入时间三级优先
    d = DATE_IN_NAME.search(Path(rel).stem)
    embedded = None
    if d:
        parts = [g for g in d.groups() if g]
        embedded = "-".join(parts) if len(parts) > 1 else parts[0]
    elif fm.get("date"):
        embedded = str(fm["date"])[:10]
    else:
        body_dates = re.findall(r"\b20\d{2}-\d{2}(?:-\d{2})?\b", raw)
        embedded = max(body_dates) if body_dates else None
    return Freshness(
        rel_path=rel, size=len(raw), embedded_date=embedded,
        declared_updated=str(fm.get("updated"))[:10] or None,
        superseded_by=str(fm.get("superseded_by") or fm.get("replaced_by") or "") or None,
        has_history_mark=bool(HIST_MARK.search(head)),
        cluster_key=cluster_of(rel))


def cluster_of(rel: str) -> str:
    """主题/项目聚类键：去日期、去序号前缀、取标题主干。"""
    stem = Path(rel).stem
    stem = DATE_IN_NAME.sub("", stem)
    stem = re.sub(r"^[\d零一二三四五六七八九十]+[-_.\s]*", "", stem)
    stem = re.sub(r"[\s_\-]+", "", stem).lower()
    return stem or Path(rel).name.lower()


def rank_cluster(members: list[Freshness]) -> tuple[str, list[str]]:
    """返回 (权威文件, 应沉底/归档列表)。S2 规则：最大者×5 倍于小者 → 小者为残骸。"""
    for m in members:
        m.is_stale_source = m.has_history_mark or bool(m.superseded_by)
    by_size = sorted(members, key=lambda x: -x.size)
    if len(by_size) >= 2 and by_size[-1].size * 5 <= by_size[0].size:
        for m in by_size[1:]:
            if m.size * 5 <= by_size[0].size:
                m.is_stale_source = True
    ranked = sorted(members, key=lambda m: (not m.authority_rank[0], ), reverse=False)
    fresh = [m for m in members if not m.is_stale_source]
    stale = [m for m in members if m.is_stale_source]
    winner = max(fresh, key=lambda m: (m.best_date or "0000", m.size)) if fresh else None
    return (winner.rel_path if winner else ""), [m.rel_path for m in stale]


# --- 簇类型学修正（2026-08-28 v1.1）：时序流 ≠ 版本簇 ---
import re as _re
_DATE_FULL = _re.compile(r"(20\d{2})-(\d{2})-(\d{2})")

def cluster_kind(members: list["Freshness"]) -> str:
    """判定簇性质：
    temporal_series 每天/每轮独立记录(早报/周报/Trending轮次) → 全保留，最新为当前态
    version         同一文档的演进副本(SDD/TDD)          → 裁决权威+沉底
    mixed           证据不足                              → 人工
    """
    dates = set()
    for m in members:
        d = _DATE_FULL.search(Path(m.rel_path).name) or (m.best_date and _DATE_FULL.search(m.best_date))
        if d: dates.add(d.group(0) if isinstance(d, str) else d.group(0))
    span_ok = len(dates) >= max(2, len(members) * 0.6)
    pathsets = {str(Path(m.rel_path).parent) for m in members}
    if span_ok and len(pathsets) <= 2:
        return "temporal_series"
    # 大小断层或历史标记 → version
    sizes = sorted((m.size for m in members), reverse=True)
    if len(sizes) >= 2 and sizes[-1] * 5 <= sizes[0]:
        return "version"
    if any(m.has_history_mark or m.superseded_by for m in members):
        return "version"
    return "mixed"
