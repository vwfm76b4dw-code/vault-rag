# -*- coding: utf-8 -*-
import os
from pathlib import Path
VAULT = Path(os.environ.get("VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault")))
DATA_DIR = Path(r"D:\AI Coding\vault-rag\data")
DB_PATH = DATA_DIR / "qwen_rag.db"
VEC_PATH = DATA_DIR / "qwen_vectors.npy"
API_URL = "http://127.0.0.1:1234/v1/embeddings"
MODEL = "text-embedding-qwen3-embedding-0.6b"
DIM = 1024
REQUEST_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF = 3
ALIVE_PROBE_TIMEOUT = 5
QUERY_INSTRUCTION = "Instruct: 给定用户的提问，从个人 Obsidian 知识库中检索最相关的笔记片段\nQuery: "
MAX_CHARS = 700
OVERLAP = 80
MIN_CHARS = 30
TOP_K = 8
P0_DIRS = ["知识", "项目", "研究"]
SKIP_DIRS = {".obsidian", ".trash", ".git", ".codex"}

# ---- Qwen3 transformers 索引器/检索器共用 ----
MODEL_NAME_QWEN = "Qwen/Qwen3-Embedding-0.6B"
QUERY_INSTRUCTION = "Instruct: 给定用户的提问，从个人 Obsidian 知识库中检索最相关的笔记片段\nQuery: "


# ---- 多模态（VL）配置（2026-08-28 新增）----
MODEL_NAME_VL = r"models/Qwen3-VL-Embedding-2B"   # 本地目录（下载完成后）
VL_DIM_MAX = 2048                                  # MRL 最大输出维
VL_DIM_USE = 1024                                  # 本期沿用文本向量维度，检索可混用；未来升维需分库
VL_QUERY_INSTRUCTION = "Instruct: 给定用户的提问，从个人知识库（含文档图像）中检索最相关的内容\nQuery: "
