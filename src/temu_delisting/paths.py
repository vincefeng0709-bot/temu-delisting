"""打包成 exe 后，"项目根目录"要怎么算是不一样的：源码运行时是仓库根目录，
打包后是 exe 所在的目录（PyInstaller onedir 模式下，`_internal` 数据文件夹
也在这个目录旁边）。config.py / accounts.py 都要用这个，不要各自算一遍。
"""
from __future__ import annotations

import sys
from pathlib import Path


def get_app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]
