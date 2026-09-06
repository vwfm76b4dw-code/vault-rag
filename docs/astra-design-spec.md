# vault-rag 控制台 UI 重做 — 设计规格书

> 对应输入包：`docs/astra-design-brief.md`  
> 实现目标：ChatGPT 风格 · 离线原生 · 不换 DOM id · 中文界面 · 8pt 网格  
> 设计日期：2026-09-06

---

## 一、全局设计令牌（CSS 变量，可直接替换 `style.css:root`）

### 1.1 色板

```css
:root {
  /* ── 中性背景层级（由深到浅） ── */
  --bg:           #0b0d0e;   /* 页面底色，纯黑偏暖 */
  --surface:      #141618;   /* 卡片/面板底色 */
  --surface2:     #1c1f21;   /* 次级嵌套（表单输入区、气泡） */
  --surface-hi:   #23272a;   /* 悬停/选中高亮区 */
  --surface-sep:  #2a2e32;   /* 分隔线 */

  /* ── 中性描边 ── */
  --line:         rgba(255,255,255,0.06);    /* 普通边框 */
  --line2:        rgba(255,255,255,0.11);    /* 次要边框（表单、列表） */
  --line-strong:  rgba(255,255,255,0.18);    /* 强调边框（聚焦、激活） */

  /* ── 文字灰阶 ── */
  --fg:       #eeeff2;     /* 主文字 */
  --fg2:      #b0b4b8;     /* 次级文字 */
  --muted:    #6b7075;     /* 辅助文字/标签 */
  --ghost:    #3d4247;     /* 禁用/占位 */

  /* ── 强调色（唯一） ── */
  --green:         #33ff33;           /* 主强调（原值保留） */
  --green-dim:     rgba(51,255,51,0.07); /* 绿色背景层 */
  --green-line:    rgba(51,255,51,0.38); /* 绿色描边 */
  --green-hover:   #66ff66;           /* 主按钮悬停 */
  --green-active:  #1fcc1f;           /* 主按钮按下 */

  /* ── 语义色（克制使用） ── */
  --warn:   #d9a04a;     /* 警告 */
  --err:    #e06c5f;     /* 错误/危险 */
  --info:   #5eaaff;     /* 信息（仅状态指示） */

  /* ── 字体 ── */
  --font:  "Segoe UI Variable", "Segoe UI", "Microsoft YaHei", sans-serif;
  --mono:  "Cascadia Code", "JetBrains Mono", "Consolas", monospace;

  /* ── 尺寸 ── */
  --radius-sm:  8px;
  --radius-md:  12px;
  --radius-lg:  16px;
  --sidebar-w:  58px;
}
```

**设计裁决**：
- `--green` 保持原值 `#33ff33`，但大面积绿色光效（极光 blob、鼠标光晕）全部移除
- 整体亮度从 `#0c0d0c` 微移至 `#0b0d0e`（更中性，不再偏绿）
- 描边统一降 opacity，从 0.07/0.13 到 0.06/0.11/0.18 三级，层次更清晰
- 绿色描边 opacity 从 0.45 降到 0.38，减少终端感，增加精致感

### 1.2 间距（8pt 网格）

| 语义 | 值 | 用途 |
|------|-----|------|
| xs | 4px | 行内微间距 |
| sm | 8px | 组件内间距 |
| md | 16px | 模块间距 |
| lg | 24px | 区块间距 |
| xl | 32px | 页面级间距 |
| 2xl | 48px | 大区块分隔 |

**面板内边距**：`padding: 18px 22px`（当前值 18/22 近似符合，改为 `20px 24px` 更饱满）

### 1.3 字阶（中文友好）

| 层级 | 字号 | 字重 | 行高 | 颜色 | 用途 |
|------|------|------|------|------|------|
| H1（页面标题） | 17px | 600 | 1.3 | var(--fg) | topbar h2 |
| H2（卡片标题） | 13px | 600 | 1.3 | var(--muted) | board-card h3 |
| 正文 | 14px | 400 | 1.6 | var(--fg) | 默认 |
| 辅助 | 12.5px | 400 | 1.5 | var(--fg2) | 次级说明 |
| 注释 | 11.5px | 400 | 1.5 | var(--muted) | 时间/分数/代码片段 |
| 极小 | 10.5px | 400 | 1.4 | var(--ghost) | 标签/分隔 |
| 等宽 | 12px | 400 | 1.55 | var(--fg) | 代码/路径 |

**设计裁决**：取消 `--radius: 12px` 全局值，改为三级圆角族（sm/md/lg）；H3 字号从 12.5px 提到 13px，字重保持 600，颜色保持 muted 以区分 H1

### 1.4 描边与阴影（近扁平）

```css
/* 卡片基础：1px 中性描边 + 无阴影 */
.glass {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-md);
  /* box-shadow: 无；分层靠 1px 描边 + 背景色差实现 */
}

/* 卡片悬停：描边颜色微变，无阴影变化 */
.glass:hover { border-color: var(--line2); }

/* 选中/激活卡片：绿色描边 + 极浅绿色背景 */
.glass.active { border-color: var(--green-line); background: var(--green-dim); }
```

**设计裁决**：
- **删除** `.glass::before` 聚光边框（鼠标跟随光晕）——视觉噪音源
- **删除** `box-shadow` 所有值——近扁平不用投影
- 分层靠：**背景色差（surface/surface2）** + **1px 描边颜色三级**

### 1.5 动效曲线

```css
--ease-out: cubic-bezier(0.32, 0.94, 0.60, 1);   /* 标准入场 */
--ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* 弹性（小幅度） */
--ease-in: cubic-bezier(0.4, 0, 1, 1);             /* 退出 */

/* 时长族 */
--dur-fast:  120ms;   /* 点击反馈 scale */
--dur-normal: 200ms;  /* hover/focus 过渡 */
--dur-slow:  280ms;   /* 面板切换 */
```

### 1.6 必须删除的装饰（从 aurora / grain / cursor-glow / glass::before）

| 元素 | 决策 | 理由 |
|------|------|------|
| `.aurora` 极光 blob（b1/b2/b3） | **删除** | 与 ChatGPT 近扁平风格冲突；视觉噪音 |
| `.grain` 噪点颗粒 | **删除** | 终端复古感，与专业工具定位不符 |
| `#cursor-glow` 鼠标光晕 | **删除** | 分散注意力，与功能界面不符 |
| `.glass::before` 聚光描边 | **删除** | 依赖 JS 写入 CSS 变量（性能浪费），视觉干扰 |
| `.nav-item.active::before` 左侧绿条 | **保留** | 清晰的当前页指示器 |
| `.dot.ok` 绿色呼吸点 | **保留**（减弱 pulse） | 功能状态指示，必要信息 |

---

## 二、组件规格

### 2.1 卡片（.board-card / .glass）

**结构**：
```html
<div class="board-card glass">
  <h3>标题 <span class="muted small">辅助</span></h3>
  <div><!-- 内容 --></div>
</div>
```

**样式要点**：
- `padding: 18px 20px`（当前 14/18，加宽到 18/20）
- `margin-bottom: 16px`（当前 14px，加到 16px 符合 8pt 网格）
- `border: 1px solid var(--line)`，悬停 `border-color: var(--line2)`
- **无阴影，无渐变背景**（删除 `.masthead` 的渐变）
- `border-radius: var(--radius-md)`（12px）

### 2.2 按钮（三态：primary / secondary / danger）

| 状态 | primary | secondary（默认） | danger |
|------|---------|-------------------|--------|
| 默认 | bg: var(--green) text: #041804 fw:600 border: transparent | bg: var(--surface2) text: var(--fg) border: 1px solid var(--line2) | bg: transparent text: var(--err) border: 1px solid rgba(224,108,95,0.35) |
| 悬停 | bg: var(--green-hover) | bg: var(--surface-hi) border: var(--line-strong) | bg: rgba(224,108,95,0.08) border: var(--err) |
| 按下 | bg: var(--green-active) scale:0.97 | scale:0.97 | scale:0.97 |
| 禁用 | opacity:0.45 cursor:default | opacity:0.45 cursor:default | opacity:0.45 cursor:default |
| 圆角 | 10px | 8px | 8px |
| 内边距 | 9px 16px | 8px 14px | 8px 14px |

**设计裁决**：primary 按钮文字颜色从纯白改为 `#041804`（深绿底配深绿字），对比度 ≥ 4.5:1

### 2.3 表单（input / textarea / select）

- `background: var(--surface2)`（当前 `rgba(0,0,0,.32)` 太深，改为 surface2）
- `border: 1px solid var(--line)` → focus 时 `border-color: var(--green-line)`
- `border-radius: var(--radius-sm)`（8px）
- `padding: 9px 12px`（当前 8/11，加到 9/12）
- `font-size: 14px`（保持）
- textarea.code：`font-family: var(--mono); font-size: 12px; line-height: 1.6`

### 2.4 列表行（.list .row / .kv .row）

- `border-bottom: 1px solid var(--line)`（当前 dashed，改为 solid 更干净）
- `padding: 7px 0`（当前 5px，加大）
- `font-size: 13px`（当前 12.5px）
- hover 行背景：`background: var(--surface-hi)`（无描边变化）

### 2.5 详情面板（#gen-detail / #emb-detail）

- `padding: 18px 20px`
- 标题 `font-size: 13px; font-weight: 600; color: var(--fg)`（当前 muted，改为 fg 提高层次）
- 字段行 `padding: 6px 0`（当前 3px，加大）
- `border-bottom: 1px solid var(--line)`（当前 dashed）

### 2.6 进度条（.pbar / .dl-bar）

- 轨道：`background: var(--line2)`（当前 0.06，加到 0.11 更清晰）
- 填充：`background: var(--green)`，`border-radius: 4px`
- 过渡：`width .4s ease-out`（当前 linear，改为 ease-out 更自然）

### 2.7 日志区（.log）

- `background: var(--surface2)`（当前 rgba(0,0,0,.35) 太黑）
- `border: 1px solid var(--line)`
- `padding: 12px 14px`（当前 9/11）
- `color: var(--fg2)`（当前 muted）
- busy 状态：`border-color: var(--green-line); color: var(--fg)`

### 2.8 空态（.empty）

- `color: var(--muted); font-size: 12.5px; padding: 20px 0; text-align: center`
- 图标可选：添加 `::before { content: "—"; margin-right: 6px; }`

### 2.9 Chip（#chips 建议气泡）

- `font-size: 12.5px; padding: 6px 14px; border-radius: 20px`（当前 8px 改圆角 pill）
- `border: 1px solid var(--line); color: var(--fg2); background: transparent`
- hover: `border-color: var(--green-line); color: var(--fg); background: var(--green-dim)`
- 取消 translateY(-1px) 微浮动（与 ChatGPT 风格不符）

### 2.10 气泡（.bubble）

- 用户气泡：`background: var(--surface2); border: 1px solid var(--line); border-radius: 18px 18px 4px 18px`（右下小圆角）
- 助手气泡：`background: var(--surface); border: 1px solid var(--line); border-left: 2px solid var(--green)`（保留当前绿条，改为 2px）
- `padding: 12px 16px`（当前 10/14，加大）
- `max-width: 80%`（当前 84%）
- `font-size: 14px; line-height: 1.65`（增加行高）

### 2.11 输入区（.chat-input-row）

- 整体：`border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface2); padding: 10px 12px; display: flex; gap: 10px; align-items: flex-end`
- textarea：`flex: 1; border: none; background: transparent; resize: none; font: inherit; padding: 0; color: var(--fg)`
- focus：`box-shadow: 0 0 0 1px var(--green-line)`（内边框，无外部描边）
- 按钮组：固定宽度 100px，垂直排列
- 发送按钮：`width: 36px; height: 36px; border-radius: 50%; background: var(--green); border: none; color: #041804; font-size: 16px`（改为圆形图标按钮）

---

## 三、8 面板布局规格

### 3.1 全局布局结构

```
.sidebar (58px 固定宽) | .content (flex:1)
                           ├── .topbar (sticky, height:52px, border-bottom)
                           └── main (flex:1, overflow:hidden)
                               └── .panel (display:none → .active display:flex/block)
```

**topbar**：
- `height: 52px; padding: 0 24px; display: flex; align-items: center; justify-content: space-between; border-bottom: 1px solid var(--line); background: var(--bg)`（删除 backdrop-filter blur）
- `#page-title`: `font-size: 15px; font-weight: 600; color: var(--fg)`
- `#topbar-info`: `font-size: 11.5px; color: var(--muted); padding: 4px 10px; border: 1px solid var(--line); border-radius: var(--radius-sm); font-family: var(--mono)`

**main 内边距**：`padding: 20px 24px`（当前 18/22）

### 3.2 侧栏交互规格（悬停展开）

**当前状态**：58px 纯图标窄栏，文字隐藏（`.sidebar .nav-item .nl { display: none; }`）

**新规格**：
- 默认：58px 纯图标（保持当前）
- 悬停侧栏（`.sidebar:hover`）：展开到 200px，显示文字标签
- 展开过渡：`width 180ms var(--ease-out); min-width: 200px`
- `.nav-item` 悬停展开时：显示 `.nl`，图标保持 22px
- `.brand .title`：展开时显示 `font-size: 14px; font-weight: 600`
- `.side-foot`：展开时显示 `#status-text`

**CSS 实现要点**：
```css
.sidebar { width: 58px; transition: width 180ms var(--ease-out); }
.sidebar:hover { width: 200px; min-width: 200px; }
.sidebar .nav-item .nl { display: none; opacity: 0; transition: opacity 150ms; }
.sidebar:hover .nav-item .nl { display: inline; opacity: 1; }
.sidebar .brand .title.nl { display: none; }
.sidebar:hover .brand .title.nl { display: inline; }
```

**JS 联动**：侧栏宽度变化不影响 `.content`（flex 自适应），无需 JS 调整

### 3.3 面板 1：问答（检索）

**布局**：
```
#panel-chat.active { display: flex; gap: 16px; }
.chat-wrap { flex: 1.6; display: flex; flex-direction: column; min-width: 0; padding: 16px; }
.sources-panel { flex: 1; min-width: 300px; max-width: 420px; padding: 16px; }
```

**chat-wrap 内部结构**（保持 DOM 不变，仅调整样式）：
- `#chat-log`：`flex: 1; overflow-y: auto; padding: 8px 8px 16px`
- 气泡间距：`margin: 14px 0`（当前 12px）
- `.chips`：`display: flex; gap: 8px; flex-wrap: wrap; padding: 0 8px 12px`
- `.chat-input-row`：`border: 1px solid var(--line); border-radius: var(--radius-md); background: var(--surface2); padding: 10px 12px; margin-top: auto; display: flex; gap: 10px; align-items: flex-end`

**sources-panel**：
- `padding: 16px`（当前 14/16）
- `h3`: `font-size: 12px; font-weight: 600; color: var(--muted); letter-spacing: 0.06em; margin-bottom: 14px`
- `.source`: `padding: 12px 14px; margin-bottom: 10px; border-radius: var(--radius-sm)`（当前 10px）
- 删除 `.source::after` 左侧绿条（改用 `.source.active` 整体绿色描边）

**功能保留**：
- `#chat-log`：气泡流、流式光标（`.stream-caret`）、复制按钮
- `#chips`：建议问题气泡
- `#chat-input`：Enter 发送 / Shift+Enter 换行
- `#btn-send` / `#btn-search-only`：发送 / 仅检索
- `#sources-panel`：来源卡、点击展开原文、PDF 页码、转笔记链接

### 3.4 面板 2：看板

**布局**：
```
#panel-board { padding: 20px 24px; }
#masthead { border-radius: var(--radius-lg); padding: 20px 24px 18px; margin-bottom: 18px; }
.cards { display: flex; gap: 14px; flex-wrap: wrap; margin-bottom: 20px; }
.card { flex: 1; min-width: 160px; padding: 18px 20px; }
.board-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px; }
```

**masthead 规格**（删除渐变背景，改为纯色）：
```css
#masthead {
  background: var(--surface);
  border: 1px solid var(--line);
  border-radius: var(--radius-lg);
  padding: 20px 24px 18px;
  margin-bottom: 18px;
  /* 删除 box-shadow 和 background: linear-gradient */
}
.mh-title { font-size: 18px; font-weight: 700; color: var(--fg); letter-spacing: 0.02em; }
.mh-title::after { height: 2px; background: var(--green-line); border-radius: 1px; }
.mh-headline { border-left-color: var(--green); background: var(--green-dim); }
.mh-cols { grid-template-columns: repeat(3, 1fr); gap: 18px; }
```

**统计卡（.card）**：
- `padding: 18px 20px`（当前 14/18）
- `.num`: `font-size: 28px; font-weight: 700; color: var(--fg); font-family: var(--mono)`（当前 26px）
- `.lbl`: `font-size: 12px; color: var(--muted); margin-top: 4px`

**领域分布条形图**：
- `.bar-row`: `margin: 10px 0`
- `.bar`: `height: 6px; background: var(--line2); border-radius: 3px`（当前 4px）
- `.bar > div`: `background: var(--green); transition: width .7s var(--ease-out)`

**知识关系图 / 权重榜 / 最近索引**：保持当前 `.kv` / `.list` 结构，仅调整字体和间距

### 3.5 面板 3：操作管理

**布局**：
```
#panel-ops { padding: 20px 24px; }
.manage-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }
```

**批量上传区**：
- `#upload-card`: `padding: 20px`
- `.dropzone`: `border: 1px dashed var(--line2); border-radius: var(--radius-md); padding: 28px; text-align: center`
- hover/drag: `border-color: var(--green-line); background: var(--green-dim)`
- 删除 `border: 2px dashed`（改为 1px）

**索引范围编辑器**：
- `#scope-text`: `rows: 18`（当前 16），`padding: 12px 14px`
- 代码字体：`font-size: 12px; line-height: 1.65`

**进度条 + 日志**：
- `.pbar`: `height: 6px; background: var(--line2)`
- `#index-log`: `height: 180px; padding: 12px 14px`

### 3.6 面板 4：仓库管理

**布局**：
```
#panel-repos { padding: 20px 24px; }
/* 四张卡片垂直排列，无 grid */
.board-card { margin-bottom: 16px; }
```

**仓库列表**（.plist）：
- 行高：`padding: 10px 0`（当前无明确定义）
- 选中态：`background: var(--green-dim); border-color: var(--green-line)`

**已索引笔记分页**：
- 搜索行：`gap: 10px`（当前 8px）
- 分页按钮：`padding: 7px 14px; border-radius: var(--radius-sm)`

### 3.7 面板 5：生成供应商

**布局**：
```
#panel-models-gen { padding: 20px 24px; }
.emb-grid { display: grid; grid-template-columns: 1fr 340px; gap: 16px; }
#gen-detail { position: sticky; top: 16px; }
```

**供应商列表**（.provider-list）：
- 行间距：`gap: 8px`（当前 7px）
- 行内边距：`padding: 12px 14px`（当前 9/13）
- 选中态：`border-color: var(--green-line); background: var(--green-dim)`

**详情面板**：
- 字段行：`padding: 7px 0; border-bottom: 1px solid var(--line)`（当前 dashed）
- 操作按钮组：`gap: 10px`（当前无明确 gap）

### 3.8 面板 6：检索 Embedding

**布局**：同面板 5（.emb-grid 复用）

**向量来源链**：
- radio 标签：`font-size: 13px; color: var(--fg)`（当前 muted）
- 选中 radio：`color: var(--green)`

**llama.cpp 状态**：
- `#llama-state`: `font-size: 11.5px; color: var(--muted)`
- 模型列表：同 .provider 样式

**HF 下载区**：
- 进度条：`.dl-bar` + `.dl-info`（保持当前 LM Studio 式样式）
- 队列提示：`#dl-queue`：`font-size: 12px; color: var(--muted); padding: 8px 0`

### 3.9 面板 7：MCP & 状态

**布局**：
```
#panel-mcp { padding: 20px 24px; }
/* 三张卡片垂直排列 */
.board-card { margin-bottom: 16px; }
```

**MCP 注册状态**：
- `#mcp-list`：plist 样式，行高 `padding: 10px 0`
- 按钮组：`gap: 10px`

**一键接入客户端**：
- `#clients-list`：同 plist
- `#snippet-box`：`border: 1px solid var(--line); border-radius: var(--radius-sm); padding: 12px 14px`

**系统状态**：
- `#mcp-sysinfo`：kv 样式，字段行 `padding: 6px 0`

### 3.10 面板 8：高级设置

**布局**：
```
#panel-settings { padding: 20px 24px; }
.two-col { display: grid; grid-template-columns: 1.2fr 1fr; gap: 16px; }
```

**生成偏好**：
- 行内标签：`.lbl-fixed`: `min-width: 80px; color: var(--muted); font-size: 13px`
- 输入框：`max-width: 100px`（当前 100px，保持）

**全局 API key**：
- 输入框：`max-width: 280px`（当前无明确限制）

**问答后端**：
- 只读字段：`background: var(--surface2); color: var(--muted); cursor: text`

**系统信息**：
- `#settings-info`：kv 样式，字段行 `padding: 7px 0`

---

## 四、质感升级专项

### 4.1 去"塑料感"方案

| 当前问题 | 解决方案 |
|----------|----------|
| 重投影（box-shadow: 0 8px 24px...） | 全部删除，改用 1px 描边 + 背景色差分层 |
| 极光 blob 模糊背景 | 删除 `.aurora` 元素及动画 |
| 噪点颗粒（.grain） | 删除 `.grain` 元素 |
| 鼠标跟随光晕 | 删除 `#cursor-glow` 及 JS 动画 |
| 玻璃卡片聚光描边（.glass::before） | 删除 ::before 伪元素及 JS 写入 CSS 变量逻辑 |
| 按钮悬停绿色发光 | 改为背景色变深 + 描边变亮，无发光 |
| 表单输入区过深黑 | 从 `rgba(0,0,0,.32)` 改为 `var(--surface2)` |

### 4.2 呼吸感增强

- 面板内边距：`20px 24px`（当前 18/22）
- 卡片间距：`16px`（当前 14px）
- 卡片内边距：`18px 20px`（当前 14/18）
- 列表行间距：`padding: 8px 0`（当前 5px）
- 按钮间距：`gap: 10px`（当前 8px）

### 4.3 中性色层次构建

用以下四级背景色构建层次，替代阴影：
1. `var(--bg)` = `#0b0d0e` — 页面底色
2. `var(--surface)` = `#141618` — 卡片/面板
3. `var(--surface2)` = `#1c1f21` — 嵌套区域（输入框、气泡）
4. `var(--surface-hi)` = `#23272a` — 悬停/选中高亮

描边三级：
1. `var(--line)` = `rgba(255,255,255,0.06)` — 普通边框
2. `var(--line2)` = `rgba(255,255,255,0.11)` — 次要边框
3. `var(--line-strong)` = `rgba(255,255,255,0.18)` — 强调边框（focus/active）

---

## 五、实现优先级

### P0：基础框架（必须完成）

| 步骤 | 内容 | 验收标准 |
|------|------|----------|
| P0-1 | 替换 `:root` 色板变量 | 控制台打开，背景无极光/噪点/光晕，卡片为中性灰 |
| P0-2 | 删除 `.aurora` `.grain` `#cursor-glow` HTML 元素 | 页面源码无这三个元素，控制台无 JS 报错 |
| P0-3 | 删除 `.glass::before` 及关联 JS（鼠标位置写入 CSS 变量） | 鼠标移动无光效，卡片边框不变 |
| P0-4 | 侧栏悬停展开（58px → 200px） | 鼠标移到侧栏，宽度平滑展开到 200px，显示文字标签 |
| P0-5 | 卡片基础样式（1px 描边 + 背景色差） | 所有 `.board-card` 无阴影，hover 仅描边变亮 |

### P1：组件规格（核心体验）

| 步骤 | 内容 | 验收标准 |
|------|------|----------|
| P1-1 | 按钮三态（primary/secondary/danger） | primary 绿色背景深绿字，hover 变亮绿，active scale(0.97) |
| P1-2 | 表单元素（input/textarea/select） | 背景 var(--surface2)，focus 绿色描边，无外部轮廓 |
| P1-3 | 气泡对话（chat） | 用户气泡右对齐圆角，助手气泡左对齐带绿条，行高 1.65 |
| P1-4 | Chip 建议（pill 形状） | 圆角 20px，hover 绿色描边 + 浅绿背景，无浮动 |
| P1-5 | 进度条（.pbar/.dl-bar） | 轨道 var(--line2)，填充 ease-out 动画 |
| P1-6 | 列表行（.list/.kv） | solid 边框，padding 8px 0，hover 背景色变深 |

### P2：面板优化（细节打磨）

| 步骤 | 内容 | 验收标准 |
|------|------|----------|
| P2-1 | 看板 masthead（删除渐变，纯色背景） | 早报卡片无渐变，无阴影，标题 18px fw:700 |
| P2-2 | 统计卡数字（font-size 28px） | 数字醒目，字重 700，mono 字体 |
| P2-3 | 来源面板（.source） | padding 12px 14px，选中态绿色描边，删除 ::after 绿条 |
| P2-4 | 输入区（.chat-input-row） | 整体圆角 12px，textarea 无 border，focus 内边框绿 |
| P2-5 | 日志区（.log） | 背景 var(--surface2)，padding 12px 14px，busy 绿色描边 |
| P2-6 | 空态（.empty） | 居中显示，color var(--muted)，padding 20px 0 |

### 验证清单（全面板检查）

- [ ] 8 个面板全部可切换，无 JS 报错
- [ ] 所有 `id` 属性保持不变（对照 index.html）
- [ ] 所有 `data-nav` 属性保持不变
- [ ] 所有事件绑定（onclick/addEventListener）正常工作
- [ ] 侧栏悬停展开/收起流畅（180ms ease-out）
- [ ] 表单输入、按钮点击、列表选择全部功能正常
- [ ] 无极光/噪点/光晕/聚光边框残留
- [ ] 中文显示正常（Segoe UI / 微软雅黑回退）
- [ ] 最小窗口 900px 下布局无溢出
- [ ] 离线可用（无 CDN 请求，无外部字体）

---

## 六、文件改动清单

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `webui_assets/style.css` | **重写** | 按本规格替换所有样式，保留所有 class/id 选择器 |
| `webui_assets/index.html` | **微调** | 删除 `.aurora` `.grain` `#cursor-glow` 三个元素 |
| `webui_assets/app.js` | **微调** | 删除光标跟随动画（约 15 行），删除 `.glass` 鼠标位置更新逻辑（约 10 行） |

**改动原则**：
- 不新增任何 HTML 元素（除删除的三个装饰元素）
- 不修改任何现有 class/id 名称
- 不添加新的 JS 依赖
- 保持 `?v=` 缓存参数纪律（版本号和文件不变）

---

## 七、验收标准（最终输出检查）

### 视觉验收
1. 页面背景纯深灰，无动画 blob、无噪点、无鼠标光晕
2. 卡片为中性灰底色 + 1px 细描边，无阴影
3. 绿色仅用于：主按钮、激活态、状态指示点、气泡左条
4. 字体层级清晰：H1 17px/600，H2 13px/600，正文 14px/400，辅助 12.5px/400
5. 间距符合 8pt 网格（8/16/20/24/32）

### 交互验收
1. 侧栏悬停展开到 200px，显示文字标签；移开收起
2. 按钮点击有 scale(0.97) 反馈
3. 表单 focus 绿色描边，无 outline
4. 气泡输入区整体圆角，无外部边框
5. 进度条动画 ease-out，无 linear 生硬感

### 功能验收
1. 8 个面板全部可切换
2. 问答：发送/仅检索/来源面板/建议 chip 全部正常
3. 看板：早报/统计卡/图表/列表全部渲染
4. 操作管理：上传/范围编辑/新建笔记/索引进度全部正常
5. 仓库管理：列表/搜索/分页/危险操作全部正常
6. 生成供应商：列表/详情/增删改/测试连通全部正常
7. 检索 Embedding：模式切换/模型列表/下载/详情全部正常
8. MCP & 状态：注册/测试/客户端接入/系统状态全部正常
9. 高级设置：偏好/Key/后端配置/系统信息全部正常

### 性能验收
1. 无额外 JS 动画循环（删除光标跟随）
2. 无 GPU 合成层滥用（删除 will-change: transform 在 blob 上）
3. 首屏渲染无阻塞（无外部资源加载）
4. 滚动流畅（60fps，无 layout thrashing）

---

## 八、设计决策记录

### D1：是否保留 `#33ff33` 荧光绿？
**决策**：保留，但大幅弱化使用范围
- 主按钮、激活态、状态点、气泡左条可用
- 禁止：大面积背景、渐变、发光、光晕
- 理由：用户指定品牌色，但当前使用过于泛滥

### D2：是否保留侧栏 58px 纯图标？
**决策**：保留默认状态，增加悬停展开交互
- 默认 58px 纯图标（与当前一致）
- 悬停展开到 200px 显示文字标签
- 理由：兼顾紧凑与可读性，符合 ChatGPT 侧栏交互

### D3：是否删除极光/噪点/光晕？
**决策**：全部删除
- 理由：与 ChatGPT 近扁平风格冲突，视觉噪音，分散注意力
- 保留：状态指示点（`.dot`）的绿色呼吸动画（减弱 pulse 强度）

### D4：是否保留玻璃卡片效果？
**决策**：保留玻璃质感，但去除聚光描边
- 保留：背景色差（surface/surface2）
- 去除：`.glass::before` 鼠标跟随光晕
- 理由：玻璃质感靠背景色差实现，无需额外光效

### D5：是否改动 DOM 结构？
**决策**：不改任何元素 id 和 class，仅删除 3 个装饰元素
- 理由：app.js 1332 行依赖现有结构，改动风险极高
- 唯一例外：删除 `.aurora` `.grain` `#cursor-glow` 三个 aria-hidden 装饰元素
