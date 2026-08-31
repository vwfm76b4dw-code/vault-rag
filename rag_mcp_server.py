# -*- coding: utf-8 -*-
"""vault-rag MCP 服务器启动入口（供 Claude Code 注册：绝对路径，无需 cwd）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from vault_rag.rag_mcp import mcp

if __name__ == "__main__":
    mcp.run()
