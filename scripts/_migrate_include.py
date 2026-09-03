# -*- coding: utf-8 -*-
"""一次性迁移：INCLUDE_PATH 静态属性 → include_path() 函数（跑完即删）。"""
from pathlib import Path

# 1) scope.py 删除 __getattr__ 兼容层
p = Path("vault_rag/scope.py")
t = p.read_text(encoding="utf-8")
old = (
    'def __getattr__(name: str):\n'
    '    """外部 `scope.INCLUDE_PATH` 兼容入口 → include_path()（动态）。"""\n'
    '    if name == "INCLUDE_PATH":\n'
    '        return include_path()\n'
    '    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")\n'
    '\n'
    '\n'
)
assert old in t, "getattr block"
t = t.replace(old, "", 1)
p.write_text(t, encoding="utf-8", newline="")
print("scope.py shim removed")

# 2) webui_lib 两处写 → include_path()
p2 = Path("vault_rag/webui_lib.py")
t2 = p2.read_text(encoding="utf-8")
pairs = [
    ('    scopes.INCLUDE_PATH.write_text(text, encoding="utf-8")',
     '    scopes.include_path().write_text(text, encoding="utf-8")'),
    ('    scopes.INCLUDE_PATH.write_text(text + sep + line + "\\n", encoding="utf-8")',
     '    scopes.include_path().write_text(text + sep + line + "\\n", encoding="utf-8")'),
]
for old, new in pairs:
    assert old in t2, old[:60]
    t2 = t2.replace(old, new, 1)
p2.write_text(t2, encoding="utf-8", newline="")
print("webui_lib -> include_path()")

# 3) tests: INCLUDE_PATH 属性补丁 → include_path 函数补丁
p3 = Path("tests/test_webui.py")
t3 = p3.read_text(encoding="utf-8")
pairs3 = [
    # TestScopeValidate.test_save_rejects_invalid
    ('''            orig = scope.INCLUDE_PATH
            scope.INCLUDE_PATH = Path(td) / "include.txt"''',
     '''            orig_ip = scope.include_path
            scope.include_path = lambda: Path(td) / "include.txt"'''),
    ('''                self.assertFalse(scope.INCLUDE_PATH.exists())   # 拒绝时不能写坏文件''',
     '''                self.assertFalse(scope.include_path().exists())   # 拒绝时不能写坏文件'''),
    ('''                self.assertTrue(scope.INCLUDE_PATH.exists())''',
     '''                self.assertTrue(scope.include_path().exists())'''),
    ('''            finally:
                scope.INCLUDE_PATH = orig''',
     '''            finally:
                scope.include_path = orig_ip'''),
]
for old, new in pairs3:
    assert old in t3, old[:60]
    t3 = t3.replace(old, new, 1)

# TestUploadEndpoint 两处 + 恢复元组里的 INCLUDE_PATH
t3 = t3.replace("orig = (ext.UPLOAD_DIR, scope.INCLUDE_PATH)",
                "orig = (ext.UPLOAD_DIR, scope.include_path)")
t3 = t3.replace("scope.INCLUDE_PATH = inc",
                "scope.include_path = lambda: inc")
t3 = t3.replace("ext.UPLOAD_DIR, scope.INCLUDE_PATH = orig",
                "ext.UPLOAD_DIR, scope.include_path = orig[1]")
# TestPerRepoInclude 断言改函数
t3 = t3.replace('self.assertEqual(scope.INCLUDE_PATH, other / "include.txt")',
                'self.assertEqual(scope.include_path(), other / "include.txt")')
p3.write_text(t3, encoding="utf-8", newline="")
print("tests -> include_path patching")
