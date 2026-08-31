# -*- coding: utf-8 -*-
"""修复 5 个僵尸 id 引用(IA 重构遗留)。"""
from pathlib import Path

p = Path("webui_assets/app.js")
t = p.read_text(encoding="utf-8")
fixes = [
    # 设置页 key 表单(新 id: modal-key* 在 settings 面板)
    ('$("btn-key-save")', '$("modal-key-save")'),
    ('$("key-input")', '$("modal-key")'),
    # 设置信息容器(新 id: settings-info)
    ('$("endpoint-info")', '$("settings-info")'),
    # 发送按钮副标签(预加载模型已移除,功能作废)与旧 pill
    ('  $("send-sub").textContent = "";\n', ''),
    ('    $("send-sub").textContent = st.model_ready ? "" : "模型加载中…";\n', ''),
]
for a, b in fixes:
    n = t.count(a)
    if n == 0: print("跳过(无引用):", a); continue
    t = t.replace(a, b)
p.write_text(t, encoding="utf-8")

# status-pill title 行单独处理(结构不同)
import re
m = re.search(r'    \$\("status-pill"\)\.title =\n(?:.*\n)*?.*?vault: \$\{st\.vault\}`;\n', t)
if m:
    t = p.read_text(encoding="utf-8")
    old = m.group(0)
    new = '    $("topbar-info").title = "上次索引: " + st.last_indexed + "\\n检索向量: " + (st.embed_ready ? "在线" : "离线(关键词模式)") + "\\n生成: " + st.chat_model + (st.chat_ready ? " ✓" : " 缺key");\n'
    t = t.replace(old, new, 1)
    p.write_text(t, encoding="utf-8")
    print("status-pill title OK")

print("修复完成")
