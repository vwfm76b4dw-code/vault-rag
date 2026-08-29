# -*- coding: utf-8 -*-
"""git_diff_scope.py — 每次 RAG 扩充前的变更发现器。

替代"全库 mtime 扫描"的粗活：与上次索引基线 commit 做 git diff，
只把真正变过的文件送进索引队列（含软链接外部源）。

工作流（全新环境直接跑 changed 即可，基线仓库自动建立）：
    python git_diff_scope.py changed     # 列出相对基线的变更/新增文件
    python git_diff_scope.py mark        # 索引完成后打新基线 tag(rag-baseline-N)
    python git_diff_scope.py status      # 显示当前基线与落后状态
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import scope as scopes
from config import VAULT

BASE_TAG = "rag-baseline"
REPO = Path(__file__).parent / ".ragfiles"


def _git_in(repo, *args) -> str:
    if not Path(repo).exists():
        return ""
    r = subprocess.run(["git", *args], cwd=str(repo), capture_output=True)
    return r.stdout.decode("utf-8", "replace")


def snapshot_files():
    """当前 include.txt 范围内的全部源文件 → {快照相对路径: (绝对路径, mtime)}。"""
    out = {}
    for rel, p in scopes.collect_files():
        if str(p).startswith(str(VAULT)):
            key = "vault/" + p.relative_to(VAULT).as_posix()
        else:
            key = "external/" + rel.split("/")[-1]   # 软链接式外部源同样纳入追踪
        out[key] = (p, p.stat().st_mtime)
    return out


def _init_and_commit(repo: Path) -> int:
    """建立快照仓库（若未初始化）并提交全量 manifest，打下一个基线 tag。"""
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", "-q"], cwd=str(repo), capture_output=True)

    def run(*a):
        subprocess.run(["git", *a], cwd=str(repo), capture_output=True, text=True)

    snap = snapshot_files()
    manifest = "\n".join(f"{k}\t{v[1]:.3f}" for k, v in sorted(snap.items()))
    (repo / "manifest.tsv").write_text(manifest, encoding="utf-8")
    run("add", "-A")
    n = len(snap)
    subprocess.run(["git", "-c", "user.name=rag", "-c", "user.email=rag@local",
                    "commit", "-q", "-m", f"baseline: {n} files"],
                   cwd=str(repo), capture_output=True)
    idx = len(_git_in(repo, "tag", "-l", BASE_TAG + "*").split())
    subprocess.run(["git", "tag", f"{BASE_TAG}-{idx+1}"], cwd=str(repo), capture_output=True)
    return idx + 1


def ensure_tracking_repo() -> bool:
    """确保 .ragfiles 快照仓库存在且有基线 tag。新建/补建返回 True。"""
    repo = REPO
    repo.mkdir(parents=True, exist_ok=True)   # Windows cwd 需真实目录
    has_tags = bool(_git_in(repo, "tag", "-l", BASE_TAG + "*").split())
    if (repo / ".git").exists() and has_tags:
        return False
    _init_and_commit(repo)
    print("[init] 已建立文件快照仓库 .ragfiles/ 并打首个基线")
    return True


def latest_baseline() -> str:
    return _git_in(REPO, "describe", "--tags", "--abbrev=0").strip()


def changed_files() -> tuple[list[tuple[str, Path]], list[str]]:
    """对比最近基线 manifest 与当前文件系统，返回 (变更清单, 删除清单)。"""
    base_tag_name = latest_baseline()
    if not base_tag_name:
        raise RuntimeError("无基线，先跑 mark")
    old = {}
    txt = _git_in(REPO, "show", f"{base_tag_name}:manifest.tsv")
    for line in txt.splitlines():
        if "\t" in line:
            k, mt = line.rsplit("\t", 1)
            old[k] = float(mt)
    cur = snapshot_files()
    result = []
    for k, (p, mt) in cur.items():
        if k not in old or abs(old[k] - mt) > 0.5:
            result.append((k, p))
    deleted = [k for k in old if k not in cur]
    return result, deleted


def cmd_changed():
    ensure_tracking_repo()
    mods, dels = changed_files()
    print(f"[changed] 修改/新增 {len(mods)} | 删除 {len(dels)}")
    for k, p in mods[:40]:
        print(f"  M {k}")
    for k in dels[:20]:
        print(f"  D {k}")
    return mods, dels


def cmd_mark():
    n = _init_and_commit(REPO)
    print(f"[mark] 新基线 rag-baseline-{n} 已记录 ({len(snapshot_files())} 文件)")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "changed":
        cmd_changed()
    elif cmd == "mark":
        cmd_mark()
    else:
        ensure_tracking_repo()
        print(_git_in(REPO, "log", "--oneline", "-5") or "(空)")
