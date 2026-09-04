# -*- coding: utf-8 -*-
"""build_exe.py — 打包 + 构建产物恢复 一体化（防漏）。

--noconfirm 会整目录清空 dist/，构建后必须恢复三件套：
  1. data_dir.txt（数据目录指针，gitignored）
  2. repos.json（仓库注册表，gitignored）
  3. llama/（内置 llama.cpp 官方预编译，gitignored）
缺一不可：漏 llama/ = 冻结版"内置 llama.cpp ✗ 未就绪"。

用法：python scripts/build_exe.py [--no-launch]
"""
import shutil
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DIST = REPO / "dist" / "vault-rag"
KEEP = ["data_dir.txt", "repos.json"]          # 构建前备份、构建后回放
LLAMA_SRC = REPO / "llama"


def main() -> int:
    no_launch = "--no-launch" in sys.argv
    backup = Path(sys.prefix) / "_vr_dist_backup"
    backup.mkdir(exist_ok=True)

    # 1) 备份
    for name in KEEP:
        src = DIST / name
        if src.exists():
            shutil.copy2(src, backup / name)
    print("已备份:", KEEP)

    # 2) 构建
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "vault-rag.spec",
                        "--noconfirm"], cwd=REPO)
    if r.returncode != 0:
        print("PyInstaller 失败"); return 1
    print("BUILD OK")

    # 3) 恢复三件套（缺这步 = 数据指针/注册表/内置 llama 全丢）
    for name in KEEP:
        b = backup / name
        if b.exists():
            shutil.copy2(b, DIST / name)
    if LLAMA_SRC.exists():
        dst_llama = DIST / "llama"
        if dst_llama.exists():
            shutil.rmtree(dst_llama)
        shutil.copytree(LLAMA_SRC, dst_llama)
    print("已恢复: data_dir.txt / repos.json / llama/")

    # 4) 自检：三件套齐 + 关键模块在包内
    missing = [n for n in KEEP if not (DIST / n).exists()]
    if not (DIST / "llama" / "llama-server.exe").exists():
        missing.append("llama/llama-server.exe")
    if missing:
        print("✗ 恢复不完整:", missing); return 1
    print("产物自检 ✓ ", DIST)

    # 5) 可选拉起（人工双击等效冒烟）
    if not no_launch:
        subprocess.Popen([str(DIST / "vault-rag.exe")], cwd=str(DIST))
        for _ in range(45):
            time.sleep(2)
            import socket
            with socket.socket() as s:
                if s.connect_ex(("127.0.0.1", 8765)) == 0:
                    print("exe UP on 8765"); break
    return 0


if __name__ == "__main__":
    sys.exit(main())
