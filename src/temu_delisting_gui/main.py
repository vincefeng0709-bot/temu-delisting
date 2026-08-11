"""GUI 入口。"""
from __future__ import annotations

import platform
import sys
from pathlib import Path

from PySide6 import __version__ as pyside6_version
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from temu_delisting.config import load_settings
from temu_delisting.logging_setup import get_logger, setup_logging

from ._version import __version__
from .widgets.main_window import MainWindow

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def _log_startup_banner() -> None:
    """在每个日志文件开头打一行"身份标识"：版本号、运行环境、是不是打包后
    的 exe 在跑——同事那边出问题发日志文件过来时，一眼就能看出是哪个版本、
    什么环境，不用来回追问。"""
    is_frozen = getattr(sys, "frozen", False)
    logger = get_logger()
    logger.info("=" * 60)
    logger.info(f"Temu 违规商品下架助手 v{__version__} 启动")
    logger.info(f"运行方式: {'打包后的 exe' if is_frozen else '源码 (python -m)'}")
    logger.info(f"操作系统: {platform.platform()}")
    logger.info(f"Python: {platform.python_version()} | PySide6: {pyside6_version}")
    logger.info("=" * 60)


def main() -> None:
    # 日志文件按进程启动时的默认账号定，这个 logger 是全局单例，进程存活期间
    # 只初始化一次（见 logging_setup.py），账号中途切换不会重新指向新账号的
    # 日志目录——这是当前的已知简化，不是 bug。
    setup_logging(load_settings().log_dir)
    _log_startup_banner()

    app = QApplication(sys.argv)
    app.setApplicationName("Temu 违规商品下架助手")

    icon_path = RESOURCES_DIR / "icons" / "app.ico"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    style_path = RESOURCES_DIR / "style.qss"
    if style_path.exists():
        icons_dir = (RESOURCES_DIR / "icons").as_posix()
        stylesheet = style_path.read_text(encoding="utf-8").replace("{ICONS_DIR}", icons_dir)
        app.setStyleSheet(stylesheet)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
