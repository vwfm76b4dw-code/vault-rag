# -*- coding: utf-8 -*-
"""带看门狗的索引执行：停滞 5 分钟自动 py-spy 抓栈 + 终止（跑完即删）。"""
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
LOG = REPO / "data" / "_index_watch.log"
STALL_SEC = 300

proc = subprocess.Popen(
    [sys.executable, "-u", "-m", "vault_rag.indexer_qwen"],
    cwd=str(REPO), stdout=open(LOG, "w", encoding="utf-8"),
    stderr=subprocess.STDOUT,
    env={**__import__("os").environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"})
print("indexer pid =", proc.pid, flush=True)

last_size, last_change = 0, time.time()
dumped = False
while True:
    time.sleep(20)
    code = proc.poll()
    size = LOG.stat().st_size
    if size != last_size:
        last_size, last_change = size, time.time()
    stall = time.time() - last_change
    tail = LOG.read_text(encoding="utf-8", errors="replace")[-120:].replace("\n", " | ")
    print(f"[{int(stall)}s 无输出] {tail}", flush=True)
    if code is not None:
        print(f"EXIT code={code}", flush=True)
        print(LOG.read_text(encoding="utf-8", errors="replace")[-600:], flush=True)
        sys.exit(0 if code == 0 else 1)
    if stall > STALL_SEC and not dumped:
        print("⚠ 停滞超过 5 分钟，py-spy 抓栈：", flush=True)
        d = subprocess.run([str(Path(sys.executable).parent / "py-spy"), "dump",
                            "--pid", str(proc.pid)], capture_output=True, text=True)
        print(d.stdout[-3000:] or d.stderr[-800:], flush=True)
        dumped = True
    if stall > STALL_SEC + 60:
        print("⚠ 抓栈后仍无进展，终止索引进程", flush=True)
        proc.kill()
        sys.exit(2)
