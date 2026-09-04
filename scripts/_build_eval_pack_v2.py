# -*- coding: utf-8 -*-
"""构建 v2 终审评审包（跑完即删）。"""
import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
report = json.load(open(REPO / "data" / "_mistake_quality_report.json", encoding="utf-8"))
vault = Path(report["sandbox_vault"])
notes = sorted((vault / "错题").glob("*.md"))
sample = []
for n in notes[:3]:
    sample.append(f"### 笔记: {n.name}\n{n.read_text(encoding='utf-8')[:700]}")
low = [r for r in report["rows"] if r.get("ok") and r.get("stem_sim", 1) < r.get("stem_thr", 0.45)]

pack = f"""# 错题管线 · 修复后终审请求（v2 指标）

## 你上轮评审的落地情况
- P0 词表全科化：已做（数学56词→全科90+词，覆盖语/数/英/物/化/道法）
- P0 M5 双评矛盾：已做——改为**验证式裁决**（把笔记声称的正确答案交给独立调用
  判 correct/wrong，不再做自由文本相似度比对）
- P1 M4 分学科阈值：已做（数学 0.60，其它 0.45；指标=达标率，阈值 0.80）
- P1 提示词加固：已做——明确"教材阅读页/知识梳理页（无学生作答）→ not_mistake"规则
  + 温度归 0。复测：上轮翻转的教材阅读页两连拒、理由标准化为"教材阅读页（无学生作答）"
- P2 source 级缓存：未做（记录为待办）

## v2 机算结果（同一 28 张混合测试集，含大量非数学页）
- ✓ M1 确定结局率 1.0 / M1b 网络残余 0 / M2 结构完整 1.0 / M3 Frontmatter 1.0 /
  M7 拒绝均带原因 1.0 / M8 复习调度 1.0
- ✗ M4 题干保真达标率 0.472（分学科阈值）
- ✗ M5 答案验证通过率 0.636（验证式独立裁决）
- ✗ M6 知识点规范性 0.455（全科词表）
- 分布：28 张 → 入库 19、拒绝 9（其中教材阅读页类拒绝理由已标准化）

## 低分样本特征
{len(low)} 篇题干相似低于其学科阈值；抽查名单：{[r['photo'][-12:] for r in low[:8]]}

## 样本笔记（前 3 篇截断）
{chr(10).join(sample)}

## 终审要求
1. v2 指标修正是否解决了你指出的口径缺陷？有没有新引入的不公平？
2. 残余的 M4/M5/M6 未达标，按数据判断：管线真实质量上限问题 or 测试集特性？
3. 给出最终可信度评分（1-5，分"纯数学场景"与"混合学科场景"两个口径）
4. 下一步最值得投入的 2 项修复。
只基于给定证据与数字，输出中文。
"""

out = REPO / "data" / "_mistake_eval_pack_v2.md"
out.write_text(pack, encoding="utf-8")
print("pack ->", out, len(pack))
