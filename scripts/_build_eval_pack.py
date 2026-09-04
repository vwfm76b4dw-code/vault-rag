# -*- coding: utf-8 -*-
"""把量化报告+样本笔记打包成评审输入，交 Claude Code 独立评价。"""
import json
from pathlib import Path

report = json.load(open(REPO := Path(__file__).resolve().parent.parent / "data" / "_mistake_quality_report.json",
                        encoding="utf-8"))
vault = Path(report["sandbox_vault"])
notes = sorted((vault / "错题").glob("*.md"))
sample = []
for n in notes[:4]:
    sample.append(f"### 笔记文件: {n.name}\n{n.read_text(encoding='utf-8')[:900]}")

pack = f"""# 错题识别管线 · 客观评审请求

## 背景
vault-rag 的错题管线：拍照 → Agnes 2.5-flash 视觉识别 → 结构化错题笔记。
量化标准见 docs/mistake-quality-rubric.md（M1-M8，阈值即通过线，双评设计）。
测试集：D:\\工作区\\测试数据 28 张真实拍照（含混入的教材内容页/非题目页）。
管线与独立双评使用同一模型（Agnes）、不同提示词。

## 本轮机算结果
- 通过 6/8：M1 确定结局率 1.0 ✓ / M1b 网络残余 0 ✓ / M2 结构完整 1.0 ✓ / M3 Frontmatter 1.0 ✓ /
  M7 拒绝均带原因 1.0 ✓ / M8 复习调度 1.0 ✓
- 未过：M4 题干保真均值 0.384（阈值 0.60）/ M5 批改双评一致性 0.053（阈值 0.80）/
  M6 知识点规范性 0.263（阈值 0.60）
- 分布：28 张 → 入库 19、明确拒绝 9；题干相似 min 0.075 / 中位 0.241 / max 0.947；
  入库中题干相似<0.2 的有 8 篇
- 跨轮稳定性问题：同一张图（94_2）上一轮被拒"不是题目（道德与法治教材页）"，
  本轮却入库成笔记（题干相似仅 0.15）——判定不稳定

## 样本笔记（前 4 篇，截断）
{chr(10).join(sample)}

## 请你客观评审（不看到图片，只基于以上文本证据）
1. 指标体系本身是否客观、可复算？有没有设计缺陷或被"做分"的空间？
2. 从报告数据推断：M4/M5/M6 未过，各自最可能的主因是【管线缺陷】还是【测试集特性】还是【指标口径缺陷】？逐项给判断和依据。
3. 对"同图跨轮判定不稳定"（94_2），你认为该用什么机制约束（温度/多数投票/明确拒绝标准）？
4. 给出修复优先级排序（管线修复 vs 指标修正 vs 提示词修正）。
5. 结论：当前错题管线对"真实学习场景"是否可信？给出 1-5 分和一句话理由。
要求：只基于给定证据，不臆测；每个判断给出可复核的依据（引用报告中的数字）。
"""

out = Path(__file__).resolve().parent.parent / "data" / "_mistake_eval_pack.md"
out.write_text(pack, encoding="utf-8")
print("pack ->", out, len(pack), "chars")
