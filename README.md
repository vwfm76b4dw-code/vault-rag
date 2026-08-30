# vault-rag — 本地优先的个人知识库 RAG 系统

把几千篇 Markdown 笔记（Obsidian Vault）变成可语义检索、可感知文档时效、可追溯版本演化的本地知识库。**纯本地推理，零云端依赖**；所有产物存放在你自己的目录，笔记原文只读不写。

## 为什么存在

通用 RAG 教程不会告诉你这些坑，它们都来自真实生产事故：

- **embedding 服务端崩溃**（`0xc0000409` 栈溢出）：llama.cpp CPU 后端对某些模型在 AVX512 关闭时不稳定；解法是用 transformers 直连模型
- **npy 向量文件三连坑**：Windows 上自动补后缀、mmap 句柄占用无法替换、全量重写覆盖失败 → 最终改为 **SQLite BLOB 存储 + 显式主键**
- **AUTOINCREMENT 主键的隐性错位**：任何一次删行之后，新向量与文本永久错序 → 改为显式主键绑定
- **文本与向量失配风险**：每批独立提交 + 启动时语义自愈（孤儿向量删、缺向量笔记回滚）
- **全库重建是个伪概念**：`hash(模型+文本)` 做 KV 缓存，任何事故后从缓存秒级自愈，增量编码零模型调用

## 架构

```
include.txt (声明式范围, .gitignore 语法)
    ↓
scope.py ── 任意目录 × 任意文件类型 → 待索引清单
    ↓
indexer_qwen.py ── 切块(chunker.py) → Qwen3-Embedding-0.6B
    ↓                ├─ embed_cache: KV 缓存（秒级自愈）
    ↓                └─ blob_vectors: 显式主键向量表
SQLite (qwen_rag.db)
    ↓
search.py / rag-obsidian MCP ── 语义检索 + 时效降权
    ↓
freshness.py + relations.py ── 时效裁决 + 四边知识关系图
    ↓
project_tree.py ── 项目知识树（mermaid 谱系图）
```

## 核心能力

### 1. 语义检索（中文强）
Qwen3-Embedding-0.6B CPU float32，官方 last-token pooling + L2 归一化 + 查询侧 instruction 前缀。3 万+ 笔记毫秒级暴力点积扫描。

### 2. 文件时效性引擎（五级信号）
mtime 不可信（批量触碰即失效），改用内容内嵌信号：
- S1 显式声明（frontmatter `superseded_by` / 「历史版本」标记）
- S2 数据量断层（同簇体积 ≥5x → 小者判残骸）
- S3 嵌入时间（文件名日期 > frontmatter > 正文三级优先）
- S4 git 基线（真实编辑史）
- S5 向量近重复（≥0.92 → 合并候选）

自动区分三种簇类型：**时序流**（早报/周报，全保留）/ **版本簇**（裁决权威+沉底残骸）/ **待人工**。

### 3. 知识关系图（四种边）
- `references` — wikilink 直通
- `supersedes` — 时效裁决（★权威 → ▽残骸）
- `sibling_next` — 时序流按日期成链
- `complements` — 跨簇向量互补

### 4. 权重机制（引用数基础 + 项目继承 + AI 评价）
```
computed = min(100, base + inherit + ai_bonus)
base     = min(in_degree × 4, 25)        # wikilink + 关系图双通道
inherit  = 项目重要度 × 0.5               # 仅根级散落文件
ai_bonus = 四维均分 × 0.5                 # structure/density/timeliness/uniqueness
```
AI 评价经 `claude -p` 无头调用，支持定期迭代（计划任务 + git 版本化）。

### 5. 多模态摄取（设计完成）
- **图像**：纹理复杂度路由（本地嵌入简单图 / 云端描述复杂图）+ 三版本原则（向量/描述/原图）
- **PDF**：pypdfium2 字符坐标聚类重建版面，双栏阅读顺序还原
- **PPTX**：zipfile+XML 零依赖抽取文本与内嵌图归属
- **数字流等非语言内容**：DataBlob 通道（元数据卡入库，不产生垃圾向量）

## 快速开始

```bash
# 0. 安装（可选，也可直接在仓库根目录运行）
pip install -e .

# 1. 配置范围（编辑 include.txt）
知识/
项目/
@/path/to/your/CLAUDE.md as external/AI工程哲学-ClaudeMd.md

# 2. 首次索引（需 LM Studio 端点或本地 transformers）
python -m vault_rag.indexer_qwen

# 3. 检索 / 问答 / 关系图 / 权重 / 知识树
python -m vault_rag.search "agent 怎么防遗忘"
python -m vault_rag.relations build
python -m vault_rag.weight_v2
python -m vault_rag.project_tree all

# 4. Web 控制台
python -m vault_rag.webui
```

## 目录结构

```
vault-rag/
├── vault_rag/            # 核心 Python 包
│   ├── config.py         #   全局配置（路径/线程/端点，环境变量可覆盖）
│   ├── scope.py          #   include.txt 解析 → 待索引清单
│   ├── chunker.py        #   markdown 语义切块
│   ├── indexer_qwen.py   #   主索引器（transformers + SQLite BLOB 向量）
│   ├── search.py         #   检索（向量链 HTTP→内置llama.cpp→关键词）
│   ├── embed_providers.py#   内置 llama.cpp 托管 + HF GGUF 下载器
│   ├── freshness.py      #   五级时效信号引擎
│   ├── relations.py      #   四边知识关系图
│   ├── weight_v2.py      #   权重机制（引用+继承+AI评价）
│   ├── project_tree.py   #   项目知识树（mermaid）
│   ├── rag_mcp.py        #   MCP 服务器
│   ├── webui.py          #   Web 控制台（FastAPI + pywebview）
│   ├── webui_lib.py      #   控制台后端逻辑
│   ├── git_diff_scope.py #   git 基线变更发现
│   ├── indexer.py        #   legacy HTTP 索引器（独立产物）
│   └── multimodal/       #   VL 多模态（实验）
├── scripts/              # 下载器/注入器/净化等运维脚本
├── tests/                # 58 用例，零 torch 依赖
├── webui_assets/         # 控制台前端（原生 HTML/CSS/JS，无框架无 CDN）
├── include.txt           # 索引范围声明（唯一事实来源）
├── stop_hook.py          # Claude Code Stop hook 入口
├── run_index.py          # 索引启动包装器（失败自愈信号）
├── vault-rag.spec        # PyInstaller 打包配置
└── pyproject.toml        # pip install -e . 入口
```

### 环境变量

| 变量 | 默认 | 说明 |
|------|------|------|
| `VAULT_PATH` | `~/Documents/Obsidian Vault` | Obsidian Vault 根目录 |
| `RAG_DATA_DIR` | `<仓库>/data` | 索引产物目录 |
| `RAG_FTS_DB` | `~/.claude/mcp_servers/obsidian-search/vault_new.db` | 外部 wikilink 图来源（可选） |
| `RAG_VEC_CACHE_MB` | `2048` | 检索向量缓存上限（MB，0=禁用） |
| `HF_ENDPOINT` | 不设置 | 代码内用 setdefault，不会覆盖你已设的镜像 |

### 依赖

```bash
pip install -r requirements.txt   # torch 建议装 CPU 版即可
```

- Python 3.10+，numpy，requests
- transformers + torch（CPU 版即可），Qwen3-Embedding-0.6B（首次运行自动经 HF 下载）
- （可选）LM Studio 1234 端口 / Obsidian MCP

### 测试

测试套件零模型依赖（纯逻辑 + SQLite 临时库），CI 在 Ubuntu/Windows × Python 3.10/3.13 上跑：

```bash
python -m unittest discover -s tests -v
```

## Web 控制台

```bash
python webui.py            # 桌面窗口（pywebview / Edge WebView2）
python webui.py --browser  # 浏览器打开
python webui.py --server   # 只起服务（远程/调试），默认 http://127.0.0.1:8765
```

四个页面：

- **问答** — 语义检索 + 云端供应商生成回答（流式，标注 [n] 引用来源，点击来源打开原文，
  回答一键复制；被时效引擎裁决取代的文档自动警示）。key 在设置面板按供应商分别保存
  （存 `data/_local_settings.json`，已 gitignore）或环境变量 `AGNES_API_KEY`。
  供应商不支持流式时自动退非流式；无 key/端点故障自动降级纯检索；
  embedding 不可用再降级关键词兜底
- **看板** — 笔记/块/向量/待索引/缓存计数、领域分布、关系图边统计、权重榜、最近索引
- **仓库** — 已索引笔记管理（搜索/分页/移出索引）、系统自检（沿 MCP 同步链路 7 项体检）、
  清空 embed 缓存 / VACUUM 压缩 / 清空索引全量重建
- **管理器** — include.txt 编辑保存（语法校验）、添加外部 @ 文件、新建笔记（自动 frontmatter）、
  触发增量索引（实时日志）

模型管理（齿轮）：**生成供应商** 10 家预设（Agnes/DeepSeek/智谱/Kimi/通义/硅基流动/
OpenRouter/OpenAI/Ollama/llama.cpp，每个档案可带独立 key，自定义档案增删改）+
生成偏好（temperature/top_k）；**检索 Embedding** 独立设置（模式四选、HTTP 端点档案
带 key、内置 llama.cpp 状态、HF GGUF 下载器 hf-mirror 可选）。外部推理：任何
OpenAI 兼容端点均可接入，本地推理（Ollama/llama.cpp/内置）无需 key。

torch 编码线程数默认 10（`RAG_TORCH_THREADS` 可调）；Windows 下所有子进程不弹控制台黑框。

## 打包为 exe

```bash
pip install pyinstaller
python -m PyInstaller vault-rag.spec --noconfirm
# 产物：dist/vault-rag/vault-rag.exe（onedir，整个文件夹即是绿色版）
```

- 双击 `vault-rag.exe` 打开控制台窗口（无控制台黑框；日志在 `data/webui.log`）
- **与 MCP/RAG 数据库联动**（任选其一）：
  1. exe 旁放一个 `data_dir.txt`（内容一行：现有 data/ 目录的绝对路径）
  2. 把 `vault-rag.exe` 放进本仓库根目录运行（data/include.txt 就用仓库里这套）
  3. 设环境变量 `RAG_DATA_DIR` 指向现有 data/、`RAG_INCLUDE` 指向 include.txt
  都不设则为全新自包含模式（产物落 exe 旁边）
- embedding 模型不打进包（运行时读 HuggingFace 缓存，首台新机器会自动经 hf-mirror 下载）
- 排除误报：PyInstaller 打包程序常被杀软误报，加入信任即可

## MCP 集成：rag-obsidian

可与现有 Obsidian FTS 服务器深度融合为 32 工具统一服务：

- `semantic_search` — 语义检索 + 时效降权内建
- `get_note_relations` — 一篇笔记的出/入关系图
- `note_freshness` — 单篇时效诊断
- （原 29 工具全部保留：FTS / 正则 / 模糊 / 拓扑 / 权重 / 维护）

设计要点：**MCP 服务器进程零重依赖**——embedding 走 HTTP 外置，失败自动降级关键词检索。

## 定时任务

- `Stop hook`：Claude Code 会话结束时自动增量索引（`git_diff_scope.py` 变更检测 → 只编真变的文件）。原子锁防并发索引器；索引进程失败时信号自动归零，变更不会被永久标记为已索引
- `每周日 03:00`：权重定期迭代（`weight_iterate.bat`，自动提交 git 版本）

## 踩坑清单（完整记录在仓库内）

1. bf16/fp8 视觉塔数值下溢 → AWQ-4bit 才是图像可用态
2. transformers 加载第三方量化需 `compressed-tensors>=0.15`
3. Windows 下 subprocess cwd 必须是已存在目录
4. LM Studio 下载走 `hf-mirror.com` + 自愈续传循环（应对 10054 断连）
5. chat_template 缺失需从 base instruct 模型注入
6. `fnmatch` 的 `*` 实际会跨目录（与 shell glob 语义相反）——include.txt 的 `*.md` 因此只匹配根级文件，跨目录请用 `**`

## License

MIT — 见 [LICENSE](LICENSE)

## 致谢与灵感

- [Qwen3-Embedding](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) / [Qwen3-VL-Embedding](https://huggingface.co/Qwen/Qwen3-VL-Embedding-2B)
- [ColPali](https://github.com/illuin-tech/colpali)（多向量晚交互检索的思想来源）
- [Docling](https://github.com/docling-project/docling) / [unstructured](https://github.com/Unstructured-IO/unstructured)（文档解析对标）
