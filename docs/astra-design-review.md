# vault-rag 控制台 UI 重做 — Round 2 评审报告

> 评审日期：2026-09-06  
> 对照规格：`docs/astra-design-spec.md`  
> 截图来源：`out/ui_review_small/`（9张 960x540）

---

## 一、总体评价

Round 2 实现已基本达到 Astra/ChatGPT 风格：中性灰背景、1px 细描边卡片、绿色强调色克制使用、侧栏悬停展开。整体质感明显优于 Round 1，"廉价感"显著降低。

## 二、已修复问题

### 2.1 问答页"仅检索"按钮竖排折行（P0）
- **证据**：`chat.jpg` / `sidebar-hover.jpg` 输入区可见
- **修复**：将 `#btn-search-only` 从圆形图标按钮改为 ghost 风格矩形按钮，宽度适应文字；`.chat-actions` 宽度从 100px 调整为 88px 并居中对齐
- **位置**：`webui_assets/style.css` 第 287-301 行

### 2.2 侧栏非激活项 hover 描边感偏重（P1）
- **证据**：`sidebar-hover.jpg` 中"检索 Embedding"项 hover 时有明显描边
- **修复**：`.nav-item:hover` 添加 `border-color: transparent` 显式覆盖，消除默认 border 透出的描边感
- **位置**：`webui_assets/style.css` 第 108 行

---

## 三、遗留问题

### 3.1 侧栏分组分隔线（.nav-cap）展开态存在感不足
- **证据**：`sidebar-hover.jpg` 展开态可见，分隔线文字 "工作台""操作管理" 等与背景融合
- **规格要求**：分组分隔线应有清晰视觉分隔
- **根因**：`.nav-cap` 仅靠 `opacity: .8` 的灰色文字区分，无辅助分隔线或背景色
- **建议**：添加 `border-top` 或 `border-bottom` 分隔线（`var(--line)`），或在展开态下背景微亮
- **优先级**：P2

### 3.2 侧栏悬停阴影过强
- **证据**：`sidebar-hover.jpg` 展开时右侧 `box-shadow: 8px 0 24px rgba(0,0,0,.35)` 明显
- **规格建议**：近扁平风格阴影应更克制
- **建议**：降低阴影强度（如 `8px 0 12px rgba(0,0,0,.2)`）或改用描边颜色变化替代
- **优先级**：P3

### 3.3 气泡底部边框残留
- **证据**：`chat.jpg` 助手气泡底部有 `border-bottom: 1px solid var(--line)`
- **规格**：气泡应为完整圆角卡片，不应有底部边框
- **根因**：CSS 中 `.bubble` 规则（约第 408 行）有 `border-bottom: 1px solid var(--line)` 残留
- **建议**：移除该边框，保持气泡完整性
- **优先级**：P2

### 3.4 卡片 h3 字重/颜色可进一步优化
- **规格要求**：H3 字号 13px / 600 / muted
- **现状**：`board-card h3` 已符合，但部分面板内 h3 可能继承默认样式
- **优先级**：P3（需全面板确认）

---

## 四、未发现问题（各面板亮点）

| 截图 | 状态 |
|------|------|
| `chat.jpg` | 气泡间距、流式光标、chip 样式均符合规格 |
| `board.jpg` | masthead 无渐变、卡片无阴影、统计卡数字 28px/mono，符合规格 |
| `ops.jpg` | 拖拽区虚线 1px、进度条 ease-out 动画正常 |
| `repos.jpg` | 列表行 solid 边框、分页按钮样式正确 |
| `models-gen.jpg` | 供应商列表选中态绿色描边+浅绿背景 |
| `models-emb.jpg` | radio 高亮、模型列表样式符合规格 |
| `mcp.jpg` | MCP 注册状态卡片样式正确 |
| `settings.jpg` | 表单输入背景 surface2、focus 绿色描边 |
| `sidebar-hover.jpg` | 展开态文字标签显示正常，除上述遗留问题外无异常 |

---

## 五、修复说明

### 已修改文件：`webui_assets/style.css`

| 修改 | 位置 | 说明 |
|------|------|------|
| `.chat-actions` 宽度+对齐 | 第 287-290 行 | width 100px→88px，添加 `align-items: center` |
| `#btn-search-only` 样式 | 第 293-301 行 | 从圆形改为圆角矩形 ghost 按钮，文字不折行 |
| `.nav-item:hover` border | 第 108 行 | 添加 `border-color: transparent` 消除悬停描边 |

### 未修改文件
- `index.html` — 无需改动（不碰 id/class/data-nav）
- `app.js` — 一行未动

---

## 六、验证建议

1. 刷新浏览器，检查"仅检索"按钮文字是否单行显示
2. hover 侧栏"检索 Embedding"项，确认无描边感
3. 展开侧栏，观察分组分隔线是否仍需增强

---

*评审完成。核心问题已修复，遗留 3 个 P2/P3 问题待后续迭代。*
