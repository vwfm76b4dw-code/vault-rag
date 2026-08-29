# -*- coding: utf-8 -*-
"""测试套件入口。运行：

    python -m unittest discover -s tests -v

设计原则：不依赖 torch / transformers / 模型文件，纯逻辑 + SQLite 内存库可跑，
CI（GitHub Actions）零下载即可验证。
"""
