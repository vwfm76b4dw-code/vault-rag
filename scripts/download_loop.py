# -*- coding: utf-8 -*-
"""自愈下载循环：崩了就续传，直到 ALL DONE。"""
import subprocess, sys, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from vault_rag.config import SUBPROCESS_FLAGS

for attempt in range(1, 40):
    r = subprocess.run([sys.executable, "download_awq.py"], cwd=str(Path(__file__).parent),
                       capture_output=True, text=True, creationflags=SUBPROCESS_FLAGS)
    if "ALL DONE" in r.stdout:
        print("DOWNLOAD COMPLETE", flush=True); break
    print(f"[loop {attempt}] retry... ({r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-80:]})", flush=True)
    time.sleep(5)
