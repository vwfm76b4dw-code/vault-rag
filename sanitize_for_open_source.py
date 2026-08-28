# -*- coding: utf-8 -*-
"""开源前净化：路径参数化、个人引用移除、内部状态出库。用户名动态获取。"""
import os
import subprocess
from pathlib import Path

USER = os.environ.get("USERNAME") or os.environ.get("USER") or "27114"
OLD_VAULT = 'VAULT = Path(r"C:\\Users\\' + USER + '\\Documents\\Obsidian Vault")'
NEW_VAULT = ('VAULT = Path(os.environ.get("VAULT_PATH", '
             'str(Path.home() / "Documents" / "Obsidian Vault")))')
IMPORT_FIX = ("from pathlib import Path\n", "import os\nfrom pathlib import Path\n")

def patch(fname, pairs, add_import=False):
    p = Path(fname)
    if not p.exists():
        return
    t = p.read_text(encoding="utf-8")
    for a, b in pairs:
        t = t.replace(a, b)
    if add_import and "import os" not in t.split("\n\n")[0][:200]:
        t = t.replace(*IMPORT_FIX, 1) if IMPORT_FIX[0] in t else t
    p.write_text(t, encoding="utf-8")

for f in ["config.py", "freshness.py", "stop_hook.py", "test_qwen.py", "hotspot_indexer.py"]:
    patch(f, [(OLD_VAULT, NEW_VAULT)], add_import=True)

patch("include.txt", [
    ("@C:\\Users\\" + USER + "\\.claude\\CLAUDE.md as external/AI工程哲学-ClaudeMd.md",
     "# @<你的 CLAUDE.md 绝对路径> as external/AI工程哲学-ClaudeMd.md  ←取消注释改成自己的"),
    ("# @C:\\Users\\" + USER + "\\.claude\\RTK.md as external/RTK-工具手册.md",
     "# @<可选其他外部文件> as external/xxx.md"),
])

patch("inject_fusion.py", [
    ('BASE = Path(r"C:\\Users\\' + USER + '\\.claude\\mcp_servers\\rag-obsidian\\server.py")',
     'BASE = Path.home() / ".claude" / "mcp_servers" / "rag-obsidian" / "server.py"'),
])

subprocess.run(["git", "rm", "-r", "--cached", "-q", ".loopx"], capture_output=True)
with open(".gitignore", "a", encoding="utf-8") as f:
    f.write("\n.loopx/\n.codex/\ndata/.last_index_signal\ndata/launcher.txt\n")

# 校验残留（脚本自身除外，它已无个人路径）
leftover = []
for p in Path(".").rglob("*"):
    if p.is_file() and p.suffix in {".py", ".txt", ".md", ".bat"} and ".git" not in p.parts:
        if p.name in {"sanitize_for_open_source.py"}:
            continue
        try:
            if USER in p.read_text(encoding="utf-8", errors="ignore"):
                leftover.append(str(p))
        except Exception:
            pass
print("残留敏感文件:", leftover or "无 ✓")
