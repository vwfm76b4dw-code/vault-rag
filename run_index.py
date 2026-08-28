import subprocess, sys
from pathlib import Path
# 用 subprocess 启动 indexer_qwen.py，输出 tee 到日志
p = subprocess.Popen(
    [sys.executable, "indexer_qwen.py"],
    stdout=open("data/index_log_qwen.txt", "w", encoding="utf-8", buffering=1),
    stderr=open("data/index_err.txt", "w", encoding="utf-8", buffering=1),
    cwd=str(Path(__file__).parent),
)
print(f"launched indexer_qwen.py PID={p.pid}")
try:
    p.wait()
except KeyboardInterrupt:
    p.terminate()
