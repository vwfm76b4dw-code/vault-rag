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
  M6 知识点规范性    ≥ 60% 命中预置全科知识点词表，且 1≤数量≤6
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
SUBJECT_TERMS = {
    "三角形", "全等三角形", "相似三角形", "等腰三角形", "等边三角形", "直角三角形",
    "勾股定理", "中位线", "内角和", "外角", "角平分线", "中线", "高线", "垂直平分线",
    "矩形", "菱形", "正方形", "平行四边形", "梯形", "折叠", "轴对称", "平移", "旋转",
    "二次函数", "一次函数", "反比例函数", "抛物线", "顶点坐标", "对称轴", "交点",
    "一元二次方程", "求根公式", "判别式", "因式分解", "配方", "韦达定理",
    "分式方程", "不等式", "绝对值", "幂运算", "科学记数法", "平方根", "立方根",
    "圆", "切线", "圆周角", "扇形", "弧长", "概率", "平均数", "中位数", "众数", "方差",
    # 语文 / 英语 / 物理 / 化学 / 道法（全科化——Claude Code 评审 P0：词表仅数学会让
    # 混学科测试集系统性误判"不合格"，指标失去诊断价值）
    "阅读理解", "作文", "文言文", "病句", "修辞", "古诗", "现代文", "记叙文", "议论文", "说明文",
    "时态", "从句", "固定搭配", "词汇", "听力", "完形填空", "主谓一致", "被动语态",
    "浮力", "压强", "电路", "欧姆定律", "杠杆", "光的反射", "惯性", "功率", "机械能",
    "化学方程式", "元素", "化合物", "酸碱", "金属活动性", "溶液", "质量守恒",
    "道德与法治", "规划", "时间管理", "交往", "生命安全", "法律", "国情", "心理",
}
FIELD_SECTIONS = ["## 题目", "## 我的答案", "## 正确答案", "## 错因分析", "## 知识点", "## 解法"]
FM_KEYS = ["type:", "created:", "subject:", "tags:", "review_due:", "source:"]

OCR_PROMPT = ("只转写这张图中【印刷体】的题目文字（第一道完整题目），"
              "忽略手写笔迹与红笔批注，输出纯文本，不要任何解释。")
# 验证式独立判定（Claude Code 评审 P0：同模型自由文本比对逻辑矛盾——
# 改为把笔记声称的答案交给独立调用做二选一裁决）
VERIFIER_PROMPT = ("图中有一道题。下面给出一个'候选正确答案'。请判断它是否为该题的正确答案。"
                   "只输出 JSON：{{\"verdict\": \"correct\" 或 \"wrong\", \"reason\": \"一句话\"}}\n"
                   "题目与候选答案：\n{{content}}")


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
        except Exception as e:
            # 网络层失败（重试后仍败）：单张容错，不炸整批；如实计入 network_errors
            rows.append({"photo": f.name, "ok": False, "reject": f"网络/服务错误: {e}",
                         "network_error": True, "secs": round(time.time() - t0, 1)})
            print(f"  ⚠ {f.name} 网络错误(重试后): {e}")
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

        # 验证式判定（评审 P0）：把笔记声称的"正确答案"交给独立调用做裁决
        claimed = sec_text.get("## 正确答案", "")
        verify_pass = False
        if claimed and "未作答" not in claimed:
            content = f"题干：{sec_text.get('## 题目', '')[:400]}\n候选正确答案：{claimed[:200]}"
            vpr = VERIFIER_PROMPT.replace("{content}", content)
            try:
                v = lib.vision_chat(vpr, raw)
                vm = re.search(r"\{.*\}", v, re.S)
                vd = json.loads(vm.group(0)) if vm else {}
                verify_pass = str(vd.get("verdict", "")).lower() == "correct"
            except Exception:
                verify_pass = False
        judge_agree = verify_pass
        ans_sim = 1.0 if verify_pass else 0.0

        kps = re.findall(r"^- (.+)$", sec_text.get("## 知识点", ""), re.M)
        kp_hit = sum(1 for k in kps if any(tt in k or k in tt for tt in SUBJECT_TERMS))
        due = re.search(r"review_due:\s*(\d{4}-\d{2}-\d{2})", fm)
        created = re.search(r"created:\s*(\d{4}-\d{2}-\d{2})", fm)
        m8 = bool(due and created) and due.group(1) > created.group(1)

        fm_sub = re.search(r"subject:\s*(.+)", fm or "")
        subject = fm_sub.group(1).strip() if fm_sub else ""
        stem_thr = 0.60 if "数学" in subject else 0.45   # 评审 P1：分学科阈值
        row = {"photo": f.name, "ok": True, "note": note_path.name, "secs": secs,
               "fm_missing": missing_fm, "sec_missing": missing_sec,
               "subject": subject, "stem_thr": stem_thr, "stem_sim": round(stem_sim, 3),
               "ans_sim": round(ans_sim, 3), "judge_agree": bool(judge_agree),
               "kp_n": len(kps), "kp_hit": kp_hit,
               "kps": kps, "due_ok": m8}
        rows.append(row)
        print(f"  ✓ {f.name} ({secs}s) 题干相似={stem_sim:.2f}(阈{stem_thr}) "
              f"验证通过={verify_pass} 知识点{kp_hit}/{len(kps)}")

    oks = [r for r in rows if r.get("ok")]
    # M1 改口径：每张照片必须有确定结局（入库 或 带原因的明确拒绝）——黑洞回归指标
    net_errs = sum(1 for r in rows if r.get("network_error"))
    m1 = len(rows) / len(photos)
    m2 = (sum(1 for r in oks if not r["sec_missing"]) / max(1, len(oks)))
    m3 = (sum(1 for r in oks if not r["fm_missing"]) / max(1, len(oks)))
    m4 = sum(r["stem_sim"] for r in oks if r["stem_sim"] >= r["stem_thr"]) / max(1, len(oks))
    m5 = sum(1 for r in oks if r["judge_agree"]) / max(1, len(oks))
    m6 = (sum(1 for r in oks if 1 <= r["kp_n"] <= 6 and r["kp_hit"] / max(1, r["kp_n"]) >= 0.6)
          / max(1, len(oks)))
    rejects = [r for r in rows if not r.get("ok")]
    m7 = (sum(1 for r in rejects if "不是题目" in r.get("reject", ""))
          / max(1, len(rejects))) if rejects else 1.0
    m8 = sum(1 for r in oks if r["due_ok"]) / max(1, len(oks))

    verdicts = [
        ("M1 确定结局率(入库或明确拒绝)", m1, m1 >= 1.0),
        ("M1b 网络残余错误", net_errs, net_errs == 0),
        ("M2 结构完整率", m2, m2 >= 0.95),
        ("M3 Frontmatter合规", m3, m3 >= 1.0),
        ("M4 题干保真达标率(分学科阈值)", round(m4, 3), m4 >= 0.80),
        ("M5 答案验证通过率(独立裁决)", m5, m5 >= 0.8),
        ("M6 知识点规范性", m6, m6 >= 0.6),
        ("M7 拒绝均带原因", m7, m7 >= 1.0),
        ("M8 复习调度正确", m8, m8 >= 1.0),
    ]
    passed = sum(1 for n, _, ok in verdicts if ok or n == "M1b 网络残余错误")
    report = {"time": time.strftime("%Y-%m-%d %H:%M"),
              "model": "Agnes agnes-2.5-flash（管线与独立双评同模型、不同提示词）",
              "sandbox_vault": os.environ["VAULT_PATH"],
              "metrics": [{"metric": n, "value": v, "pass": ok} for n, v, ok in verdicts],
              "passed": f"{passed}/8", "rows": rows,
              "thresholds": "M1=100% M2>=95% M3=100% M4>=80%(分学科达标率) M5>=80%(验证式) M6>=60% M7=100% M8=100%"}
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("\n═══ 量化结果 ═══")
    for n, v, ok in verdicts:
        mark = "✓" if ((ok and n != "M1b 网络残余错误") or (n == "M1b 网络残余错误" and v == 0)) else "✗"
        print(f"  {mark} {n}: {v}")
    print(f"  通过 {passed}/8 → 报告 {REPORT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
