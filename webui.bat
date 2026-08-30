@echo off
REM vault-rag Web 控制台启动器（桌面窗口）
REM 用法：双击；或命令行 webui.bat --browser（浏览器模式）/ --server（仅服务）
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
python webui.py %*
pause
