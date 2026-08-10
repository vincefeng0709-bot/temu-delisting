"""GUI 入口。"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from .widgets.main_window import MainWindow

RESOURCES_DIR = Path(__file__).resolve().parent / "resources"


def main() -> None:
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
