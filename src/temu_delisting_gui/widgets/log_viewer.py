"""日志查看窗口：测试同事在自己电脑上遇到问题时打开这个窗口，把日志内容
复制发过来分析，不用去翻文件夹、不用知道日志文件具体存在哪个路径。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)


class LogViewerDialog(QDialog):
    def __init__(self, log_dir: Path, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("查看日志文件")
        self.resize(820, 600)
        self._log_dir = log_dir

        layout = QVBoxLayout(self)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("日志文件："))
        self.file_combo = QComboBox()
        self.file_combo.setMinimumWidth(220)
        self.file_combo.currentIndexChanged.connect(self._load_selected_file)
        top_row.addWidget(self.file_combo, stretch=1)

        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._reload_file_list)
        top_row.addWidget(refresh_button)

        copy_button = QPushButton("复制全部")
        copy_button.setObjectName("primaryButton")
        copy_button.clicked.connect(self._copy_all)
        top_row.addWidget(copy_button)
        layout.addLayout(top_row)

        self.text_area = QPlainTextEdit()
        self.text_area.setReadOnly(True)
        self.text_area.setObjectName("logPanel")
        layout.addWidget(self.text_area, stretch=1)

        self._reload_file_list()

    def _reload_file_list(self) -> None:
        previous_name = self.file_combo.currentText()
        self.file_combo.blockSignals(True)
        self.file_combo.clear()

        files = (
            sorted(self._log_dir.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            if self._log_dir.exists()
            else []
        )
        for f in files:
            self.file_combo.addItem(f.name, userData=str(f))
        self.file_combo.blockSignals(False)

        if not files:
            self.text_area.setPlainText("（还没有日志文件——先跑一次扫描或下架，再回来看）")
            return

        index = self.file_combo.findText(previous_name)
        self.file_combo.setCurrentIndex(index if index >= 0 else 0)
        self._load_selected_file()

    def _load_selected_file(self) -> None:
        path_text = self.file_combo.currentData()
        if not path_text:
            return
        try:
            content = Path(path_text).read_text(encoding="utf-8")
        except OSError as exc:
            content = f"读取日志文件失败：{exc}"
        self.text_area.setPlainText(content)
        scrollbar = self.text_area.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def _copy_all(self) -> None:
        QApplication.clipboard().setText(self.text_area.toPlainText())
        QMessageBox.information(self, "复制全部", "日志内容已复制到剪贴板，可以直接粘贴发出去了。")
