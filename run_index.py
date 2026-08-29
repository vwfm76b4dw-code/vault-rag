# -*- coding: utf-8 -*-
"""索引启动包装器（Stop hook / 手动运行共用）。

- 运行 indexer_qwen.py，输出追加到 data/index_log_qwen.txt（带时间戳分隔）
- 退出码非 0（崩溃/中断）时把 .last_index_signal 归零：
  触发时 hook 已把信号写成当时的 vault 最新 mtime，若不归零，
  本批变更会被永久标记为"已索引"而再也不被拾起
- 无论成败都释放 stop_hook.py 的运行锁
"""
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
LOG = BASE / "data" / "index_log_qwen.txt"
ERR = BASE / "data" / "index_err.txt"
SIGNAL = BASE / "data" / ".last_index_signal"
LOCK = BASE / "data" / "index_running.lock"


def main() -> int:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y-%m-%d %H:%M:%S")
    p = None
    try:
        with open(LOG, "a", encoding="utf-8", buffering=1) as out, \
                open(ERR, "a", encoding="utf-8", buffering=1) as err:
            out.write(f"\n===== index start {stamp} =====\n")
            p = subprocess.Popen(
                [sys.executable, str(BASE / "indexer_qwen.py")],
                stdout=out, stderr=err, cwd=str(BASE),
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
            code = p.wait()
            out.write(f"===== index exit {code} =====\n")
    except KeyboardInterrupt:
        code = 130
        if p is not None and p.poll() is None:
            p.terminate()
    finally:
        LOCK.unlink(missing_ok=True)     # 释放 hook 锁（幂等：不存在也无妨）

    if code != 0:
        SIGNAL.write_text("0.0")         # 失败归零：下次会话结束重新拾起本批变更
        with open(ERR, "a", encoding="utf-8") as err:
            err.write(f"[{stamp}] index failed (exit {code}), signal reset to 0\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
