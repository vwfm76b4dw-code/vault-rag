# -*- coding: utf-8 -*-
"""自愈下载循环：崩了就续传，直到 ALL DONE。"""
import subprocess, sys, time
from pathlib import Path
for attempt in range(1, 40):
    r = subprocess.run([sys.executable, "download_awq.py"], cwd=str(Path(__file__).parent),
                       capture_output=True, text=True)
    if "ALL DONE" in r.stdout:
        print("DOWNLOAD COMPLETE", flush=True); break
    print(f"[loop {attempt}] retry... ({r.stdout.strip().splitlines()[-1] if r.stdout.strip() else r.stderr[-80:]})", flush=True)
    time.sleep(5)
