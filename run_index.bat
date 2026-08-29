@echo off
REM vault-rag 索引启动器 —— 脱离 Claude Code 会话树独立运行
REM 用法：双击或在 cmd 里运行，索引进程不会因 Claude Code 会话中断被杀
REM 走 run_index.py（indexer_qwen 增量索引，SQLite BLOB 主库）
REM 注意：legacy 的 indexer.py --rebuild 会重建独立的 data\rag.db，不要对主库做 rebuild
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
REM 用 start 新建独立窗口 + 进程树，与当前 shell 解耦
start "vault-rag-index" cmd /c "python run_index.py & pause"
echo 已启动独立索引窗口。查看进度：type "%~dp0data\index_log_qwen.txt"
