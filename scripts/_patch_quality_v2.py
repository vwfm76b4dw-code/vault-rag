# -*- coding: utf-8 -*-
"""一次性补丁 v2b：M5 改验证式判定 + M4 分学科阈值（跑完即删）。"""
from pathlib import Path

p = Path("scripts/mistake_quality_test.py")
t = p.read_text(encoding="utf-8")

old = '''        # 独立双评（同图、不同提示词、独立调用）
        ocr_ref = ""
        try:
            ocr_ref = lib.vision_chat(OCR_PROMPT, raw).strip()
        except Exception as e:
            ocr_ref = f"<OCR失败 {type(e).__name__}>"
        stem_sim = sim(sec_text.get("## 题目", ""), ocr_ref)

        grader = {}
        try:
            g = lib.vision_chat(GRADER_PROMPT, raw)
            gm = re.search(r"\\{.*\\}", g, re.S)
            grader = json.loads(gm.group(0)) if gm else {}
        except Exception as e:
            grader = {"error": str(e)[:80]}
        ans_sim = sim(sec_text.get("## 正确答案", ""), str(grader.get("correct_answer", "")))
        note_concl = "作答正确" in sec_text.get("## 错因分析", "")
        g_judg = str(grader.get("judgment", ""))
        judge_agree = (note_concl and g_judg == "right") or ((not note_concl) and g_judg == "wrong")

        kps = re.findall(r"^- (.+)$", sec_text.get("## 知识点", ""), re.M)
        kp_hit = sum(1 for k in kps if any(t in k or k in t for t in MATH_TERMS))
        due = re.search(r"review_due:\\s*(\\d{4}-\\d{2}-\\d{2})", fm)
        created = re.search(r"created:\\s*(\\d{4}-\\d{2}-\\d{2})", fm)
        m8 = bool(due and created) and due.group(1) > created.group(1)

        row = {"photo": f.name, "ok": True, "note": note_path.name, "secs": secs,
               "fm_missing": missing_fm, "sec_missing": missing_sec,
               "stem_sim": round(stem_sim, 3),
               "ans_sim": round(ans_sim, 3), "judge_agree": bool(judge_agree),
               "kp_n": len(kps), "kp_hit": kp_hit,
               "kps": kps, "due_ok": m8}'''

new = '''        # 独立双评（同图、不同提示词、独立调用）
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
            content = f"题干：{sec_text.get('## 题目', '')[:400]}\\n候选正确答案：{claimed[:200]}"
            vpr = VERIFIER_PROMPT.replace("{content}", content)
            try:
                v = lib.vision_chat(vpr, raw)
                vm = re.search(r"\\{.*\\}", v, re.S)
                vd = json.loads(vm.group(0)) if vm else {}
                verify_pass = str(vd.get("verdict", "")).lower() == "correct"
            except Exception:
                verify_pass = False
        judge_agree = verify_pass
        ans_sim = 1.0 if verify_pass else 0.0

        kps = re.findall(r"^- (.+)$", sec_text.get("## 知识点", ""), re.M)
        kp_hit = sum(1 for k in kps if any(tt in k or k in tt for tt in SUBJECT_TERMS))
        due = re.search(r"review_due:\\s*(\\d{4}-\\d{2}-\\d{2})", fm)
        created = re.search(r"created:\\s*(\\d{4}-\\d{2}-\\d{2})", fm)
        m8 = bool(due and created) and due.group(1) > created.group(1)

        fm_sub = re.search(r"subject:\\s*(.+)", fm or "")
        subject = fm_sub.group(1).strip() if fm_sub else ""
        stem_thr = 0.60 if "数学" in subject else 0.45   # 评审 P1：分学科阈值
        row = {"photo": f.name, "ok": True, "note": note_path.name, "secs": secs,
               "fm_missing": missing_fm, "sec_missing": missing_sec,
               "subject": subject, "stem_thr": stem_thr, "stem_sim": round(stem_sim, 3),
               "ans_sim": round(ans_sim, 3), "judge_agree": bool(judge_agree),
               "kp_n": len(kps), "kp_hit": kp_hit,
               "kps": kps, "due_ok": m8}'''

assert old in t, "dual-grade block not found"
t = t.replace(old, new, 1)

old4 = '''    m4 = sum(r["stem_sim"] for r in oks) / max(1, len(oks))
    m5 = sum(1 for r in oks if r["ans_sim"] >= 0.5 and r["judge_agree"]) / max(1, len(oks))'''
new4 = '''    m4 = sum(r["stem_sim"] for r in oks if r["stem_sim"] >= r["stem_thr"]) / max(1, len(oks))
    m5 = sum(1 for r in oks if r["judge_agree"]) / max(1, len(oks))'''
assert old4 in t, "m4/m5"
t = t.replace(old4, new4, 1)

for old5, new5 in [
    ('        ("M4 题干保真度(均值)", round(m4, 3), m4 >= 0.60),',
     '        ("M4 题干保真达标率(分学科阈值)", round(m4, 3), m4 >= 0.80),'),
    ('        ("M5 批改双评一致性", m5, m5 >= 0.8),',
     '        ("M5 答案验证通过率(独立裁决)", m5, m5 >= 0.8),'),
    ('              "thresholds": "M1=100% M2>=95% M3=100% M4>=0.60 M5>=80% M6>=60% M7=100% M8=100%"}',
     '              "thresholds": "M1=100% M2>=95% M3=100% M4>=80%(分学科达标率) M5>=80%(验证式) M6>=60% M7=100% M8=100%"}'),
    ('''        print(f"  ✓ {f.name} ({secs}s) 题干相似={stem_sim:.2f} 答案相似={ans_sim:.2f} "
              f"判定一致={judge_agree} 知识点{kp_hit}/{len(kps)}")''',
     '''        print(f"  ✓ {f.name} ({secs}s) 题干相似={stem_sim:.2f}(阈{stem_thr}) "
              f"验证通过={verify_pass} 知识点{kp_hit}/{len(kps)}")'''),
    ('    "kp_hit": kp_hit', '    "kp_hit": kp_hit'),  # no-op guard
]:
    if old5 in t:
        t = t.replace(old5, new5, 1)

# 词表改名（全科）
t = t.replace("MATH_TERMS = {", "SUBJECT_TERMS = {")
t = t.replace("for t in MATH_TERMS", "for tt in SUBJECT_TERMS")
t = t.replace("命中预置初中数学词表", "命中预置全科知识点词表")

p.write_text(t, encoding="utf-8", newline="")
print("metrics v2b patched")
