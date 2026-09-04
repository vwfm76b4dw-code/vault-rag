# -*- coding: utf-8 -*-
"""mistake.py — 错题本：拍照 → 视觉模型识别批改 → 结构化错题笔记 → 入库可检索。

灵魂功能「持续复利」的入口：上传页拖入图片即走本链路，
笔记落 vault/错题/（scope 自动覆盖），frontmatter 带 review_due 供复习提醒。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from vault_rag.config import VAULT

MISTAKE_DIR = "错题"
_NOT_MISTAKE_KEYS = ("not_mistake",)


class MistakeError(Exception):
    """视觉识别/笔记生成失败（信息面向最终用户展示）。"""


VISION_PROMPT = """你是错题整理助手。识别图片中的题目（可能是拍照的试卷/练习，含手写作答）；若图中有多道题，只取第一道完整题目。只输出严格 JSON（不要 markdown 代码块以外的任何文字）：
{"subject": "学科", "topic_tags": ["标签"], "question": "题干完整转写（数学式用 $...$）", "my_answer": "图中学生的作答，未作答则为空字符串", "correct_answer": "正确答案", "error_reason": "错因分析（若未作答则写未作答的原因推测）", "knowledge_points": ["涉及知识点"], "solution": "完整正确解法步骤"}
如果图片是教材/教辅的【阅读页、知识梳理页、课文页】——即没有可供批改的学生作答——也视为不是题目，输出：{"not_mistake": true, "description": "教材阅读页（无学生作答）"}。区分标准：有明确的题目+可判定的作答=错题；纯知识梳理/课文/规划建议=非题目。"""


def _json_repair(t: str) -> str:
    """常见视觉 JSON 病灶的保守修复：尾逗号、字符串内裸换行。"""
    t = re.sub(r",\s*([}\]])", r"\1", t)                       # 尾逗号
    t = re.sub(r'(:\s*"[^"\n]*)\n([^"\n]*")', r"\1\\n\2", t)   # 串内裸换行 → \n
    return t


def parse_vision_json(text: str) -> dict:
    """解析视觉模型输出：剥代码围栏、取第一个 JSON 对象，失败做保守修复重试。"""
    t = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", t, re.S)
    if m:
        t = m.group(1)
    else:
        m = re.search(r"\{.*\}", t, re.S)
        if m:
            t = m.group(0)
    try:
        data = json.loads(t)
    except json.JSONDecodeError:
        try:
            data = json.loads(_json_repair(t))
        except json.JSONDecodeError as e:
            raise MistakeError(f"视觉模型输出不是合法 JSON：{e}") from e
    if not isinstance(data, dict):
        raise MistakeError("视觉模型输出结构异常")
    return data


def _slug(text: str, fallback: str = "题") -> str:
    t = re.sub(r"[^\w\u4e00-\u9fff-]+", "-", (text or "").strip()).strip("-")
    return (t or fallback)[:24]


def build_note(data: dict, source_name: str, vault: Path | None = None) -> tuple[Path, dict]:
    """把解析后的题目数据写成错题笔记，返回 (路径, 预览)。"""
    if not (data.get("question") or "").strip():
        raise MistakeError("识别结果缺少题干，放弃入库")
    vault = vault or VAULT
    kp = [str(x).strip() for x in (data.get("knowledge_points") or []) if str(x).strip()]
    tags = [str(x).strip() for x in (data.get("topic_tags") or []) if str(x).strip()]
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = _slug(kp[0] if kp else data.get("subject") or data.get("topic_tags"))
    rel = f"{MISTAKE_DIR}/{stamp}-{name}.md"
    target = vault / MISTAKE_DIR / f"{stamp}-{name}.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    today = time.strftime("%Y-%m-%d")
    due = time.strftime("%Y-%m-%d", time.localtime(time.time() + 86400))
    body = f"""---
type: mistake
created: {today}
subject: {data.get("subject") or ""}
tags: [{", ".join(["错题", *tags])}]
review_due: {due}
source: {source_name}
---

# 错题 · {kp[0] if kp else data.get("subject") or "待归类"}

## 题目

{data.get("question") or ""}

## 我的答案

{data.get("my_answer") or "（未作答）"}

## 正确答案

{data.get("correct_answer") or ""}

## 错因分析

{data.get("error_reason") or ""}

## 知识点

{chr(10).join(f"- {x}" for x in kp) if kp else "（未识别）"}

## 解法

{data.get("solution") or ""}
"""
    target.write_text(body, encoding="utf-8")
    preview = {"subject": data.get("subject") or "", "knowledge_points": kp,
               "question": (data.get("question") or "")[:80],
               "error_reason": (data.get("error_reason") or "")[:120]}
    return target, preview


def due_reviews(vault: Path | None = None, limit: int = 8) -> list[dict]:
    """扫描错题 frontmatter，返回今天及以前到期的复习清单（头条用）。"""
    import re as _re
    vault = vault or VAULT
    today = time.strftime("%Y-%m-%d")
    out = []
    d = vault / MISTAKE_DIR
    if not d.exists():
        return out
    for p in sorted(d.glob("*.md"), key=lambda x: x.stat().st_mtime):
        if len(out) >= limit:
            break
        try:
            head = p.read_text(encoding="utf-8")[:400]
        except OSError:
            continue
        m = _re.search(r"review_due:\s*(\d{4}-\d{2}-\d{2})", head)
        s = _re.search(r"subject:\s*(.+)", head)
        if m and m.group(1) <= today:
            out.append({"rel": f"{MISTAKE_DIR}/{p.name}",
                        "due": m.group(1),
                        "subject": (s.group(1).strip() if s else "")})
    return out


def ingest(image_bytes: bytes, source_name: str, vision_fn=None,
           vault: Path | None = None) -> tuple[Path, dict]:
    """图片 → 视觉识别 → 错题笔记。vision_fn(prompt, image_bytes) -> str 可注入测试。"""
    if vision_fn is None:
        from vault_rag import webui_lib as lib
        vision_fn = lambda pr, im: lib.vision_chat(pr, im, temperature=0.0)  # 判定要确定性的

    def _call_with_retry(prompt: str, tries: int = 3) -> str:
        """瞬时网络/网关错误（502/超时）指数退避重试；解析错误不在此层重试。"""
        last = None
        for i in range(tries):
            try:
                return vision_fn(prompt, image_bytes)
            except Exception as e:            # ChatUnavailable / 网络层
                last = e
                if i < tries - 1:
                    time.sleep(3 * (i + 1))
        raise last

    raw = _call_with_retry(VISION_PROMPT)
    try:
        data = parse_vision_json(raw)
    except MistakeError:
        # 一次性纠正重试：把坏输出喂回去要求修成合法 JSON（成本 1 次调用，救回整题）
        fixed = vision_fn("以下 JSON 不合法，请修正为严格合法 JSON 后只输出 JSON：\n" + raw[:2000])
        data = parse_vision_json(fixed)
    if any(k in data for k in _NOT_MISTAKE_KEYS):
        desc = data.get("description") or "非题目内容"
        raise MistakeError(f"图片不是题目（识别为：{desc}），未入库")
    return build_note(data, source_name, vault=vault)
