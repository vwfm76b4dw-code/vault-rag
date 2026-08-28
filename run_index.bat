@echo off
REM vault-rag 索引启动器 —— 脱离 Claude Code 会话树独立运行
REM 用法：双击或在 cmd 里运行，索引进程不会因 Claude Code 会话中断被杀
cd /d "D:\AI Coding\vault-rag"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
REM 用 start 新建独立窗口 + 进程树，与当前 shell 解耦
start "vault-rag-index" cmd /c "python indexer.py --rebuild > data\index_log.txt 2>&1 & echo DONE >> data\index_log.txt & pause"
echo 已启动独立索引窗口。查看进度：type "D:\AI Coding\vault-rag\data\index_log.txt"
