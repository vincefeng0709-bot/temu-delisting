# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 配置：把分机端提交程序（temu_delisting_satellite）打成一个
onedir 应用。这台机器不需要登录 Temu、不需要 Playwright，只负责往共享
文件夹里丢任务请求文件、回来看结果，所以体积比主程序小很多、打包也快很多。

用法（在项目根目录、激活好 .venv 之后）：
    pyinstaller packaging/temu_delisting_satellite.spec --distpath dist --workpath build

产物在 dist/TemuDelistingSatellite/ 下，里面的 TemuDelistingSatellite.exe
就是给分机操作人员双击运行的程序。整个文件夹要一起打包发过去（onedir 模式
下依赖文件都在同一个文件夹里，不能只发 exe 单个文件）。
"""

from pathlib import Path

PROJECT_ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 — SPECPATH 是 PyInstaller 注入的内置变量

a = Analysis(  # noqa: F821
    [str(PROJECT_ROOT / "packaging" / "satellite_entrypoint.py")],
    pathex=[str(PROJECT_ROOT / "src")],
    binaries=[],
    datas=[
        (str(PROJECT_ROOT / "src" / "temu_delisting_satellite" / "resources"), "temu_delisting_satellite/resources"),
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
    name="TemuDelistingSatellite",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # 不弹黑色命令行窗口，操作人员只会看到 GUI 窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(PROJECT_ROOT / "src" / "temu_delisting_satellite" / "resources" / "icons" / "app.ico"),
    # 用扁平目录结构（不套一层 _internal 子文件夹），跟主程序保持一致。
    contents_directory=".",
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TemuDelistingSatellite",
)
