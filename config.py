# -*- coding: utf-8 -*-
"""全局配置。所有路径可用环境变量覆盖，仓库内不再出现机器特定绝对路径。

环境变量：
    VAULT_PATH      Obsidian Vault 根目录（默认 ~/Documents/Obsidian Vault）
    RAG_DATA_DIR    索引产物目录（默认 <BASE_DIR>/data）
    RAG_FTS_DB      外部 Obsidian FTS 库路径（可选，供 relations/weights 读 wikilink）
    HF_ENDPOINT     HuggingFace 镜像（代码内一律 setdefault，不覆盖用户已设值）

BASE_DIR：开发态 = 仓库根；PyInstaller 打包后 = exe 所在目录。
把 vault-rag.exe 放进仓库目录（或设 RAG_DATA_DIR）即可与 MCP 共用同一套数据库。
"""
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent
BASE_DIR = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else _REPO

VAULT = Path(os.environ.get("VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault")))


def _resolve_data_dir() -> Path:
    """优先级：RAG_DATA_DIR 环境变量 > exe 旁 data_dir.txt 指针（一行路径）> exe旁 data/。"""
    env = os.environ.get("RAG_DATA_DIR")
    if env:
        return Path(env)
    pointer = BASE_DIR / "data_dir.txt"
    if pointer.is_file():
        try:
            p = Path(pointer.read_text(encoding="utf-8").strip())
            if p.is_dir():
                return p
        except OSError:
            pass
    return BASE_DIR / "data"


DATA_DIR = _resolve_data_dir()

# ---- 当前主索引（SQLite BLOB 向量，见 indexer_qwen.py）----
DB_PATH = DATA_DIR / "qwen_rag.db"
RELATIONS_DB = DATA_DIR / "relations.db"
WEIGHTS_DB = DATA_DIR / "weights.db"

# ---- legacy HTTP 索引器（indexer.py / test_qwen.py，独立产物，与主库互不影响）----
LEGACY_DB_PATH = DATA_DIR / "rag.db"
LEGACY_VEC_PATH = DATA_DIR / "vectors.npy"
API_URL = "http://127.0.0.1:1234/v1/embeddings"
MODEL = "text-embedding-qwen3-embedding-0.6b"
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 3
ALIVE_PROBE_TIMEOUT = 5

# ---- embedding 模型与检索 ----
MODEL_NAME_QWEN = "Qwen/Qwen3-Embedding-0.6B"
DIM = 1024
QUERY_INSTRUCTION = "Instruct: 给定用户的提问，从个人 Obsidian 知识库中检索最相关的笔记片段\nQuery: "
TOP_K = 8

# ---- 切块 ----
MAX_CHARS = 700
OVERLAP = 80
MIN_CHARS = 30

P0_DIRS = ["知识", "项目", "研究"]
SKIP_DIRS = {".obsidian", ".trash", ".git", ".codex"}

# ---- 外部 Obsidian FTS 库（wikilink 图来源，可选）----
FTS_DB = Path(os.environ.get(
    "RAG_FTS_DB", str(Path.home() / ".claude/mcp_servers/obsidian-search/vault_new.db")))

# ---- 线程与子进程 ----
# torch 编码线程数：默认 10（过高在部分机器上会引发崩溃，见 README 踩坑清单）
TORCH_THREADS = int(os.environ.get("RAG_TORCH_THREADS", "10"))
# Windows 子进程统一不弹控制台黑框（DETACHED/无父控制台的子进程会自建 console）
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
SUBPROCESS_FLAGS = CREATE_NO_WINDOW

# ---- 问答生成（OpenAI 兼容；默认国内站 Agnes，可切 llama.cpp 等本地端点）----
CHAT_API_URL = os.environ.get(
    "RAG_CHAT_API_URL", "https://api.agnes-ai.cn/v1/chat/completions")
CHAT_MODEL = os.environ.get("RAG_CHAT_MODEL", "agnes-2.5-flash")
CHAT_API_KEY_ENVS = ("AGNES_API_KEY", "AGNES_KEY")
CHAT_TIMEOUT = int(os.environ.get("RAG_CHAT_TIMEOUT", "120"))
# 本地密钥文件（gitignored）：{"agnes_key": "sk-..."}，可在 Web 控制台管理页设置
LOCAL_SETTINGS_PATH = DATA_DIR / "_local_settings.json"

# ---- Web 控制台 ----
WEBUI_HOST = os.environ.get("RAG_WEBUI_HOST", "127.0.0.1")
WEBUI_PORT = int(os.environ.get("RAG_WEBUI_PORT", "8765"))

# ---- 多模态（VL）配置 ----
MODEL_NAME_VL = "models/Qwen3-VL-Embedding-2B"     # 本地目录（下载完成后）
VL_DIM_MAX = 2048                                  # MRL 最大输出维
VL_DIM_USE = 1024                                  # 本期沿用文本向量维度，检索可混用；未来升维需分库
VL_QUERY_INSTRUCTION = "Instruct: 给定用户的提问，从个人知识库（含文档图像）中检索最相关的内容\nQuery: "
