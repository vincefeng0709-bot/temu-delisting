# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置：把 temu_delisting_gui 打成一个 onedir 应用。

用法（在项目根目录、激活好 .venv 之后）：
    pyinstaller packaging/temu_delisting_gui.spec --distpath dist --workpath build

产物在 dist/TemuDelisting/ 下，里面的 TemuDelisting.exe 就是给同事双击运行
的主程序。整个 dist/TemuDelisting/ 文件夹要一起打包发给对方（压缩成 zip
发过去，不能只发 exe 单个文件——onedir 模式下依赖文件都在同一个文件夹里）。

不需要打包 Chromium 浏览器内核（browser.py 用的是 channel="chrome"，直接
调用系统里已装的 Google Chrome），但 Playwright 自己的 driver（内含一份
独立的 node.exe，约100MB，不依赖系统 Node.js）会被官方 PyInstaller hook
自动收集进来，不用我们手动配置。
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH 是 PyInstaller 注入的内置变量

a = Analysis(  # noqa: F821
    [str(PROJECT_ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "config" / "violation_types.yaml"), "config"),
        (str(PROJECT_ROOT / "src" / "temu_delisting_gui" / "resources"), "temu_delisting_gui/resources"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="TemuDelisting",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 不弹黑色命令行窗口，同事只会看到 GUI 窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
    # 用扁平目录结构（不套一层 _internal 子文件夹）：get_app_root() 假定
    # config/、data/ 这些都跟 exe 在同一层，跟源码运行时的目录结构保持一致。
    contents_directory=".",
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TemuDelisting",
)
