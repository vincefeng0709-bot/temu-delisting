"""GUI 入口。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from temu_delisting.config import load_settings
from temu_delisting.logging_setup import setup_logging

from .widgets.main_window import MainWindow

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def main() -> None:
    # 日志文件按进程启动时的默认账号定，这个 logger 是全局单例，进程存活期间
    # 只初始化一次（见 logging_setup.py），账号中途切换不会重新指向新账号的
    # 日志目录——这是当前的已知简化，不是 bug。
    setup_logging(load_settings().log_dir)

    app = QApplication(sys.argv)
    app.setApplicationName("Temu 违规商品下架助手")

    style_path = RESOURCES_DIR / "style.qss"
    if style_path.exists():
        app.setStyleSheet(style_path.read_text(encoding="utf-8"))

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
