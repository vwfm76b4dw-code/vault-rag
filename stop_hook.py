# -*- coding: utf-8 -*-
"""vault-rag Stop hook — Claude Code 会话结束时自动增量索引 RAG。

成熟模式要点（参考 github.com/Rsprux/claude-code-hooks-mastery 等）：
1. 不阻塞 Stop：同步只做 mtime 短路判断，真实索引用 DETACHED 子进程派生后立即退出
2. 幂等短路：vault 最新 mtime <= 上次信号 → 秒退（大部分会话是这种情况）
3. 防死循环：消费 stop_hook_active 标志
4. 防并发：原子锁文件（O_EXCL），已有索引进程在跑则本次跳过（下次会话结束再触发）
5. 失败自愈：子进程失败时 run_index.py 会把信号归零，变更不会被永久标记为已索引
6. 全量留痕：data/index_auto.log 追加日志
7. 干跑模式：--check 只打印决策不改状态

用法：
    python stop_hook.py          # 作为 Stop hook 被 Claude Code 调用（stdin 收 JSON）
    python stop_hook.py --check  # 手动干跑，只报告会不会触发
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))
from config import CREATE_NO_WINDOW
VAULT = Path(os.environ.get("VAULT_PATH", str(Path.home() / "Documents" / "Obsidian Vault")))
SIGNAL = BASE / "data" / ".last_index_signal"
LOG = BASE / "data" / "index_auto.log"
LOCK = BASE / "data" / "index_running.lock"
LOCK_STALE_SECONDS = 6 * 3600   # 锁超过 6 小时视为残留（崩溃未清理）


def log(msg: str):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")


def vault_latest_mtime() -> float:
    """扫描 vault 所有 md 的最大 mtime（跳过隐藏目录）。"""
    latest = 0.0
    for p in VAULT.rglob("*.md"):
        rel = p.relative_to(VAULT)
        if any(part.startswith(".") for part in rel.parts):
            continue
        try:
            mt = p.stat().st_mtime
            if mt > latest:
                latest = mt
        except OSError:
            continue
    return latest


def acquire_lock() -> bool:
    """原子获取索引锁；残留死锁（超时）则清理后重试一次。"""
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"{time.time():.3f}".encode())
            os.close(fd)
            return True
        except FileExistsError:
            try:
                age = time.time() - LOCK.stat().st_mtime
                if age > LOCK_STALE_SECONDS:
                    log(f"stale lock removed (age={age/3600:.1f}h)")
                    LOCK.unlink(missing_ok=True)
                    continue
            except OSError:
                continue
            return False
    return False


def main() -> int:
    check_only = "--check" in sys.argv

    # 成熟模式 3：必须消费 stdin 的 hook payload，并尊重防循环标志
    try:
        payload = json.load(sys.stdin)
    except Exception:
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    latest = vault_latest_mtime()
    last = 0.0
    if SIGNAL.exists():
        try:
            last = float(SIGNAL.read_text().strip())
        except ValueError:
            last = 0.0

    # 成熟模式 2：确定性短路——没新东西就别动 python 重武器
    if latest <= last + 0.5:
        msg = f"no changes (last={last:.0f}, latest={latest:.0f})"
        print(msg)
        if not check_only:
            log(msg)
        return 0

    action = (f"changes detected (last={last:.0f}, latest={latest:.0f})"
              f" -> would spawn incremental index")
    if check_only:
        print("[dry-run] " + action)
        return 0

    if not acquire_lock():
        msg = "index already running, skip this trigger (will retry next session end)"
        print(msg)
        log(msg)
        return 0

    # 成熟模式 1：DETACHED 派生真实索引，主进程立刻返回不阻塞会话退出
    flags = 0
    if os.name == "nt":
        flags = (subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                 | CREATE_NO_WINDOW)
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}
    child = subprocess.Popen(
        [sys.executable, str(BASE / "run_index.py")],
        cwd=str(BASE),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        env=env,
    )
    SIGNAL.write_text(f"{latest:.6f}")
    done_msg = action.replace("would spawn", "spawned")
    print(done_msg + f" pid={child.pid}")
    log(done_msg + f" pid={child.pid}")   # 成熟模式 4：留痕
    return 0


if __name__ == "__main__":
    sys.exit(main())
