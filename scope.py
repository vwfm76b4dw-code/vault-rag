# -*- coding: utf-8 -*-
"""scope.py — 解析 include.txt，产出待索引文件清单（vault 内 + 外部）。

include.txt 语法见该文件头部注释。匹配器语义：
- 规则按行序生效，后写的 '!排除' 覆盖先写的包含
- 目录规则 'dir/' = 前缀匹配该目录下所有内容
- glob 用 fnmatch（* 不跨目录）；'**' 支持跨目录段
"""
import fnmatch
import re
from pathlib import Path

from config import VAULT

INCLUDE_PATH = Path(__file__).parent / "include.txt"

Rule = tuple  # ("include"|"exclude", pattern) / ("external", abs_path, alias)


def parse_rules(text: str | None = None) -> list[Rule]:
    text = (Path(INCLUDE_PATH).read_text(encoding="utf-8")) if text is None else text
    rules: list[Rule] = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("@"):
            body = line[1:]
            alias = None
            if " as " in body:
                body, alias = body.split(" as ", 1)
                alias = alias.strip()
            abs_path = Path(body.strip().strip('"'))
            if not abs_path.is_absolute():
                raise ValueError(f"@ 外部路径必须是绝对路径: {line}")
            rules.append(("external", str(abs_path), alias))
        elif line.startswith("!"):
            rules.append(("exclude", _compile(line[1:].strip())))
        else:
            rules.append(("include", _compile(line)))
    return rules


def _compile(pattern: str):
    """返回 f(rel_posix_lower) -> bool 的判定函数。"""
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        pl = prefix.lower()
        return lambda rp: rp.lower().startswith(pl + "/")
    # 根级文件通配（如 *.md）：fnmatch 本身不跨目录（* 不匹配 /），正好符合语义
    pl = pattern.lower()
    return lambda rp: fnmatch.fnmatchcase(rp.lower(), pl)


def collect_files() -> list[tuple[str, Path]]:
    """解析 include.txt → [(rel_path 用于入库显示, 绝对 Path)]。

    - vault 内文件以相对 POSIX 路径标识
    - 外部 @ 文件以 'external/...' 别名标识
    """
    rules = parse_rules()
    out: dict[str, Path] = {}

    for rule in rules:
        kind = rule[0]
        if kind == "exclude":
            pred = rule[1]
            out = {rp: p for rp, p in out.items() if not pred(rp)}
            continue

        candidates: list[tuple[str, Path]] = []
        if kind == "include":
            pred = rule[1]
            for p in VAULT.rglob("*.md"):
                rel = p.relative_to(VAULT).as_posix()
                if any(part.startswith(".") for part in rel.split("/")):
                    continue          # 隐藏目录永远不进候选池
                if pred(rel):
                    candidates.append((rel, p))
        else:  # external
            _, abs_str, alias = rule
            ap = Path(abs_str)
            if not ap.exists():
                continue              # 外部文件不存在则静默跳过（日志由调用方负责）
            name = alias or ("external/" + ap.name)
            candidates.append((name, ap))

        for rel, p in candidates:
            out[rel] = p

    return sorted(out.items())


def external_names() -> set[str]:
    """所有外部别名（供 search 结果识别来源）。"""
    return {rule[2] or ("external/" + Path(rule[1]).name)
            for rule in parse_rules() if rule[0] == "external"}
