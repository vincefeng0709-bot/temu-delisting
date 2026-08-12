"""审核清单：勾选确认/跳过要不要下架，支持导出 Excel 留档。

未知违规类型（needs_human_review）默认不勾选、整行标黄提醒——避免同事在
不知情的情况下把没见过的违规类型也一并确认下架。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from temu_delisting.classifier import DELIST_SUGGESTED, NEEDS_HUMAN_REVIEW
from temu_delisting.config import Settings
from temu_delisting.store import Suggestion, open_store

COLUMN_LABELS = ["确认下架", "SPU ID", "违规类型", "分类", "违规详情"]
NEEDS_REVIEW_COLOR = QColor("#fff3cd")


class ReviewTableWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._settings: Settings | None = None
        self._batch_id: str | None = None
        self._suggestions: list[Suggestion] = []
        self._checkboxes: dict[int, QCheckBox] = {}

        layout = QVBoxLayout(self)

        self.info_label = QLabel("还没有可审核的数据，先去「运行」页扫描一次。")
        self.info_label.setObjectName("hintLabel")
        layout.addWidget(self.info_label)

        self.table = QTableWidget(0, len(COLUMN_LABELS))
        self.table.setHorizontalHeaderLabels(COLUMN_LABELS)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        layout.addWidget(self.table, stretch=1)

        button_row = QHBoxLayout()
        self.select_suggested_button = QPushButton("只勾选「建议下架」的")
        self.select_suggested_button.clicked.connect(self._select_suggested_only)

        self.export_button = QPushButton("导出 Excel")
        self.export_button.clicked.connect(self._on_export)

        self.save_button = QPushButton("保存审核结果")
        self.save_button.setObjectName("primaryButton")
        self.save_button.clicked.connect(self._on_save)

        button_row.addWidget(self.select_suggested_button)
        button_row.addStretch(1)
        button_row.addWidget(self.export_button)
        button_row.addWidget(self.save_button)
        layout.addLayout(button_row)

    def load(
        self,
        settings: Settings,
        batch_id: str,
        suggestions: list[Suggestion],
        total_from_page: int | None = None,
        raw_row_count: int | None = None,
        unique_spu_count: int | None = None,
    ) -> None:
        self._settings = settings
        self._batch_id = batch_id
        self._suggestions = suggestions
        self._checkboxes = {}

        self.table.setRowCount(len(suggestions))
        for row, suggestion in enumerate(suggestions):
            checkbox = QCheckBox()
            checkbox.setChecked(suggestion.classification == DELIST_SUGGESTED)
            self._checkboxes[row] = checkbox
            self.table.setCellWidget(row, 0, checkbox)

            label = "建议下架" if suggestion.classification == DELIST_SUGGESTED else "待人工判断"
            values = [
                suggestion.spu_id,
                suggestion.violation_type,
                label,
                suggestion.violation_detail[:200],
            ]
            for col_offset, value in enumerate(values, start=1):
                item = QTableWidgetItem(value)
                if suggestion.classification == NEEDS_HUMAN_REVIEW:
                    item.setBackground(NEEDS_REVIEW_COLOR)
                self.table.setItem(row, col_offset, item)

        stats_parts = [f"批次 {batch_id}"]
        stats_parts.append(f"网页显示总数 {total_from_page}" if total_from_page is not None else "网页总数未知")
        stats_parts.append(f"实际抓取 {raw_row_count if raw_row_count is not None else len(suggestions)} 条")
        if unique_spu_count is not None:
            stats_parts.append(f"去重后 {unique_spu_count} 个不同 SPU")
        self.info_label.setText(
            "，".join(stats_parts) + "。黄色底色是没见过的违规类型，请谨慎确认；"
            "同一个 SPU 出现多条一般是它在不同国家/地区分别违规，下架时会自动识别已处理过的，不用担心重复。"
        )

    # -- 操作 --------------------------------------------------------

    def _select_suggested_only(self) -> None:
        for row, suggestion in enumerate(self._suggestions):
            self._checkboxes[row].setChecked(suggestion.classification == DELIST_SUGGESTED)

    def _on_export(self) -> None:
        if not self._suggestions:
            QMessageBox.information(self, "导出 Excel", "还没有数据可以导出，先扫描一次。")
            return

        default_name = f"{self._batch_id}.xlsx"
        path, _ = QFileDialog.getSaveFileName(self, "导出 Excel", default_name, "Excel 文件 (*.xlsx)")
        if not path:
            return

        try:
            self._export_xlsx(Path(path))
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导出失败", f"导出失败，请重试：{exc}")
            return

        QMessageBox.information(self, "导出成功", f"已导出到：\n{path}")

    def _export_xlsx(self, path: Path) -> None:
        from openpyxl import Workbook

        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "审核清单"
        sheet.append(["SPU ID", "违规类型", "违规详情", "分类", "是否确认下架"])

        for row, suggestion in enumerate(self._suggestions):
            confirmed = self._checkboxes[row].isChecked()
            label = "建议下架" if suggestion.classification == DELIST_SUGGESTED else "待人工判断"
            sheet.append(
                [
                    suggestion.spu_id,
                    suggestion.violation_type,
                    suggestion.violation_detail,
                    label,
                    "是" if confirmed else "否",
                ]
            )

        workbook.save(path)

    def _on_save(self) -> None:
        if not self._suggestions or self._settings is None:
            QMessageBox.information(self, "保存审核结果", "还没有数据可以保存，先扫描一次。")
            return

        confirmed_count = 0
        with open_store(self._settings.db_path) as store:
            for row, suggestion in enumerate(self._suggestions):
                status = "confirmed" if self._checkboxes[row].isChecked() else "rejected"
                store.set_review_status(suggestion.id, status)
                if status == "confirmed":
                    confirmed_count += 1

        QMessageBox.information(
            self,
            "保存成功",
            f"已保存审核结果，共确认 {confirmed_count} 条待下架。\n"
            f"下一步：在「运行」页点「开始下架」即可执行。",
        )
