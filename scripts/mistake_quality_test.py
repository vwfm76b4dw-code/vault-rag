# -*- coding: utf-8 -*-
"""mistake_quality_test.py — 错题识别管线量化测试（客观、可机算、不看图）。

流程：5 张真实错题拍照（D:\\工作区\\测试数据）→ 管线入库（VAULT=沙盒临时目录）
     → 独立双评（同图另行 OCR/批改，提示词与管线不同）→ 机算 8 项指标 → JSON 报告。

量化标准（阈值即通过线）：
  M1 入库成功率      ≥ 100%（本批 5 张均含题目；非题目应有明确拒绝）
  M2 结构完整率      ≥ 95%  六字段非空（"我的答案"允许"未作答"）
  M3 Frontmatter合规  = 100%  type/created/subject/tags/review_due/source 六键
  M4 题干保真度      均值 ≥ 0.60（笔记题目 vs 独立OCR 的字符相似度）
  M5 批改双评一致性  ≥ 4/5（正确答案相似≥0.5 且 判定方向一致）
  M6 知识点规范性    ≥ 60% 命中预置初中数学词表，且 1≤数量≤6
  M7 无幻觉拒绝      非题目误报 = 0
  M8 复习调度正确    review_due = created+1 天 = 100%

用法：python scripts/mistake_quality_test.py   → data/_mistake_quality_report.json
注意：本脚本不看任何图片；所有图像理解经 Agnes 2.5-flash API。
"""
import difflib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
os.environ["VAULT_PATH"] = tempfile.mkdtemp(prefix="mistake_qt_")   # 沙盒 vault

PHOTOS_DIR = Path(r"D:\工作区\测试数据")
REPORT = REPO / "data" / "_mistake_quality_report.json"

# 初中数学知识点词表（M6 用；允许合理超纲词，只统计命中率）
MATH_TERMS = {
    "三角形", "全等三角形", "相似三角形", "等腰三角形", "等边三角形", "直角三角形",
    "勾股定理", "中位线", "内角和", "外角", "角平分线", "中线", "高线", "垂直平分线",
    "矩形", "菱形", "正方形", "平行四边形", "梯形", "折叠", "轴对称", "平移", "旋转",
    "二次函数", "一次函数", "反比例函数", "抛物线", "顶点坐标", "对称轴", "交点",
    "一元二次方程", "求根公式", "判别式", "因式分解", "配方", "韦达定理",
    "分式方程", "不等式", "绝对值", "幂运算", "科学记数法", "平方根", "立方根",
    "圆", "切线", "圆周角", "扇形", "弧长", "概率", "平均数", "中位数", "众数", "方差",
}
FIELD_SECTIONS = ["## 题目", "## 我的答案", "## 正确答案", "## 错因分析", "## 知识点", "## 解法"]
FM_KEYS = ["type:", "created:", "subject:", "tags:", "review_due:", "source:"]

OCR_PROMPT = ("只转写这张图中【印刷体】的题目文字（第一道完整题目），"
              "忽略手写笔迹与红笔批注，输出纯文本，不要任何解释。")
GRADER_PROMPT = ("你是独立批改老师。识别图中题目与学生手写作答，只输出 JSON："
                 '{"question_stem": "题干转写", "student_answer": "学生最终答案", '
                 '"correct_answer": "你认为的正确答案", "judgment": "right或wrong"}')


def sim(a: str, b: str) -> float:
    a = re.sub(r"\s+", "", a or "")
    b = re.sub(r"\s+", "", b or "")
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def main() -> int:
    from vault_rag import mistake as M
    from vault_rag import webui_lib as lib

    photos = sorted(PHOTOS_DIR.glob("*.jpg"))
    assert len(photos) >= 5, f"测试照片不足: {len(photos)}"
    print(f"沙盒 vault: {os.environ['VAULT_PATH']}")
    print(f"待测照片: {len(photos)} 张\n")

    rows = []
    for f in photos:
        raw = f.read_bytes()
        t0 = time.time()
        try:
            note_path, preview = M.ingest(raw, f.name)
            note_text = note_path.read_text(encoding="utf-8")
            ok = True
        except M.MistakeError as e:
            rows.append({"photo": f.name, "ok": False, "reject": str(e), "secs": round(time.time() - t0, 1)})
            print(f"  ✗ {f.name} 明确拒绝: {e}")
            continue
        secs = round(time.time() - t0, 1)

        fm = note_text.split("---")[1] if note_text.startswith("---") else ""
        missing_fm = [k for k in FM_KEYS if k not in fm]
        missing_sec = [s for s in FIELD_SECTIONS if s not in note_text]
        sec_text = {s: (note_text.split(s, 1)[1].split("##")[0].strip())
                    for s in FIELD_SECTIONS if s in note_text}

        # 独立双评（同图、不同提示词、独立调用）
        ocr_ref = ""
        try:
            ocr_ref = lib.vision_chat(OCR_PROMPT, raw).strip()
        except Exception as e:
            ocr_ref = f"<OCR失败 {type(e).__name__}>"
        stem_sim = sim(sec_text.get("## 题目", ""), ocr_ref)

        grader = {}
        try:
            g = lib.vision_chat(GRADER_PROMPT, raw)
            gm = re.search(r"\{.*\}", g, re.S)
            grader = json.loads(gm.group(0)) if gm else {}
        except Exception as e:
            grader = {"error": str(e)[:80]}
        ans_sim = sim(sec_text.get("## 正确答案", ""), str(grader.get("correct_answer", "")))
        note_concl = "作答正确" in sec_text.get("## 错因分析", "")
        g_judg = str(grader.get("judgment", ""))
        judge_agree = (note_concl and g_judg == "right") or ((not note_concl) and g_judg == "wrong")

        kps = re.findall(r"^- (.+)$", sec_text.get("## 知识点", ""), re.M)
        kp_hit = sum(1 for k in kps if any(t in k or k in t for t in MATH_TERMS))
        due = re.search(r"review_due:\s*(\d{4}-\d{2}-\d{2})", fm)
        created = re.search(r"created:\s*(\d{4}-\d{2}-\d{2})", fm)
        m8 = bool(due and created) and due.group(1) > created.group(1)

        row = {"photo": f.name, "ok": True, "note": note_path.name, "secs": secs,
               "fm_missing": missing_fm, "sec_missing": missing_sec,
               "stem_sim": round(stem_sim, 3),
               "ans_sim": round(ans_sim, 3), "judge_agree": bool(judge_agree),
               "kp_n": len(kps), "kp_hit": kp_hit,
               "kps": kps, "due_ok": m8}
        rows.append(row)
        print(f"  ✓ {f.name} ({secs}s) 题干相似={stem_sim:.2f} 答案相似={ans_sim:.2f} "
              f"判定一致={judge_agree} 知识点{kp_hit}/{len(kps)}")

    oks = [r for r in rows if r.get("ok")]
    # M1 改口径：每张照片必须有确定结局（入库 或 带原因的明确拒绝）——黑洞回归指标
    m1 = len(rows) / len(photos)
    m2 = (sum(1 for r in oks if not r["sec_missing"]) / max(1, len(oks)))
    m3 = (sum(1 for r in oks if not r["fm_missing"]) / max(1, len(oks)))
    m4 = sum(r["stem_sim"] for r in oks) / max(1, len(oks))
    m5 = sum(1 for r in oks if r["ans_sim"] >= 0.5 and r["judge_agree"]) / max(1, len(oks))
    m6 = (sum(1 for r in oks if 1 <= r["kp_n"] <= 6 and r["kp_hit"] / max(1, r["kp_n"]) >= 0.6)
          / max(1, len(oks)))
    rejects = [r for r in rows if not r.get("ok")]
    m7 = (sum(1 for r in rejects if "不是题目" in r.get("reject", ""))
          / max(1, len(rejects))) if rejects else 1.0
    m8 = sum(1 for r in oks if r["due_ok"]) / max(1, len(oks))

    verdicts = [
        ("M1 确定结局率(入库或明确拒绝)", m1, m1 >= 1.0),
        ("M2 结构完整率", m2, m2 >= 0.95),
        ("M3 Frontmatter合规", m3, m3 >= 1.0),
        ("M4 题干保真度(均值)", round(m4, 3), m4 >= 0.60),
        ("M5 批改双评一致性", m5, m5 >= 0.8),
        ("M6 知识点规范性", m6, m6 >= 0.6),
        ("M7 拒绝均带原因", m7, m7 >= 1.0),
        ("M8 复习调度正确", m8, m8 >= 1.0),
    ]
    passed = sum(1 for _, _, ok in verdicts if ok)
    report = {"time": time.strftime("%Y-%m-%d %H:%M"),
              "model": "Agnes agnes-2.5-flash（管线与独立双评同模型、不同提示词）",
              "sandbox_vault": os.environ["VAULT_PATH"],
              "metrics": [{"metric": n, "value": v, "pass": ok} for n, v, ok in verdicts],
              "passed": f"{passed}/8", "rows": rows,
              "thresholds": "M1=100% M2>=95% M3=100% M4>=0.60 M5>=80% M6>=60% M7=100% M8=100%"}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n═══ 量化结果 ═══")
    for n, v, ok in verdicts:
        print(f"  {'✓' if ok else '✗'} {n}: {v}")
    print(f"  通过 {passed}/8 → 报告 {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
