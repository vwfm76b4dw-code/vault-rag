# -*- coding: utf-8 -*-
"""scope.py — 解析 include.txt，产出待索引文件清单（vault 内 + 外部）。

include.txt 语法见该文件头部注释。匹配器语义：
- 规则按行序生效，后写的 '!排除' 覆盖先写的包含
- 目录规则 'dir/' = 前缀匹配该目录下所有内容
- glob 用 fnmatch（* 不跨目录）；'**' 支持跨目录段
- vault 内文件：最后一条命中的规则决定去留（include 收 / exclude 排）
- 外部 @ 文件：在其规则位置加入，之后出现的 exclude 规则仍可将其排除
"""
import os
import re
import shutil
import sys
from pathlib import Path

from vault_rag.config import VAULT, BASE_DIR

INCLUDE_PATH = Path(os.environ["RAG_INCLUDE"]) if os.getenv("RAG_INCLUDE") \
    else BASE_DIR / "include.txt"

Rule = tuple  # ("include"|"exclude", pred) / ("external", abs_path, alias)


def ensure_include_file() -> Path:
    """include.txt 不存在时自举（打包态从随包模板复制，开发态仓库本就有）。"""
    if INCLUDE_PATH.exists():
        return INCLUDE_PATH
    bundled = Path(getattr(sys, "_MEIPASS", "")) / "include.txt" \
        if getattr(sys, "frozen", False) else None
    if bundled and bundled.exists():
        shutil.copy(bundled, INCLUDE_PATH)
    else:
        INCLUDE_PATH.write_text(
            "# vault-rag 索引范围声明（.gitignore 语法）\n"
            "#   目录规则 'dir/' | 文件 'path/to.md' | 通配 '*.md'（仅根级，跨目录用 '**'）\n"
            "#   '!排除' | '@绝对路径 as external/别名.md'（vault 外部文件）\n\n"
            "知识/\n项目/\n研究/\n笔记/\n*.md\n",
            encoding="utf-8")
    return INCLUDE_PATH


def _glob_to_rx(pat: str) -> str:
    """glob → 正则：'**' 跨目录段，'*'/'?' 不跨目录（fnmatch 的 * 会跨，语义不符）。"""
    out, i = [], 0
    while i < len(pat):
        c = pat[i]
        if c == "*":
            if i + 1 < len(pat) and pat[i + 1] == "*":
                out.append(".*")
                i += 2
                continue
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return "".join(out)


def parse_rules(text: str | None = None) -> list[Rule]:
    if text is None:
        ensure_include_file()
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
    """返回 f(rel_posix) -> bool 的判定函数。"""
    pattern = pattern.lstrip("/")
    if pattern.endswith("/"):
        prefix = pattern.rstrip("/")
        pl = prefix.lower()
        return lambda rp: rp.lower().startswith(pl + "/")
    # 文件通配：'*' 不跨目录（*.md 只匹配根级），'**' 才跨目录，见 include.txt 语法说明
    rx = re.compile(_glob_to_rx(pattern.lower()))
    return lambda rp: rx.fullmatch(rp.lower()) is not None


def _iter_vault_md():
    """单次扫描 vault 全部 md（隐藏目录除外）。"""
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT).as_posix()
        if any(part.startswith(".") for part in rel.split("/")):
            continue          # 隐藏目录永远不进候选池
        yield rel, p


def collect_files(rules: list[Rule] | None = None,
                  include_uploads: bool = True) -> list[tuple[str, Path]]:
    """解析 include.txt → [(rel_path 用于入库显示, 绝对 Path)]。

    - vault 内文件以相对 POSIX 路径标识
    - 外部 @ 文件以 'external/...' 别名标识
    - rules 可注入（测试用），默认读 include.txt
    """
    rules = parse_rules() if rules is None else rules
    out: dict[str, Path] = {}

    # vault 内：单次扫描，逐文件找最后一条命中规则（O(文件数×规则数)，规则通常 <20）
    ext_rules: list[tuple[int, str, str | None]] = []
    for idx, rule in enumerate(rules):
        if rule[0] == "external":
            ext_rules.append((idx, rule[1], rule[2]))

    for rel, p in _iter_vault_md():
        verdict = None                      # 最后命中的规则类型
        for idx, rule in enumerate(rules):
            if rule[0] == "include" and rule[1](rel):
                verdict = "include"
            elif rule[0] == "exclude" and rule[1](rel):
                verdict = "exclude"
        if verdict == "include":
            out[rel] = p

    # 外部：按规则序加入，其后的 exclude 仍可排除（与旧行为一致）
    for idx, abs_str, alias in ext_rules:
        ap = Path(abs_str)
        if not ap.exists():
            continue              # 外部文件不存在则静默跳过（日志由调用方负责）
        name = alias or ("external/" + ap.name)
        if any(rule[0] == "exclude" and rule[1](name)
               for rule in rules[idx + 1:]):
            continue
        out[name] = ap

    # 上传目录整目录自动纳入（不依赖 @ 规则——避免 include.txt 编辑/切换时丢失）
    from vault_rag.config import DATA_DIR
    uploads = DATA_DIR / "uploads"
    if include_uploads and uploads.exists():
        for p in sorted(uploads.rglob("*")):
            if p.is_file():
                rel = "uploads/" + p.relative_to(uploads).as_posix()
                out.setdefault(rel, p)

    return sorted(out.items())


def external_names() -> set[str]:
    """所有外部别名（供 search 结果识别来源）。"""
    return {rule[2] or ("external/" + Path(rule[1]).name)
            for rule in parse_rules() if rule[0] == "external"}
