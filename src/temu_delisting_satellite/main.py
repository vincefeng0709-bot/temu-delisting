"""分机端 GUI 入口——独立于主程序，不需要 Playwright/登录态，只负责往共享
文件夹里提交任务请求、回来看结果。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .widgets.main_window import MainWindow

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Temu 下架任务提交端")

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
