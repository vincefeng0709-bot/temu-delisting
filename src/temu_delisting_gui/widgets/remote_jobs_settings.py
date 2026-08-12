"""「接口程序」设置页：配置共享文件夹路径 + 开关 + 并发上限，外加一份可以
手动调整顺序的排队清单。

分机（每个店铺一台的小机器）把任务请求文件丢进共享文件夹里对应账号的
子文件夹，这台主机（跑这个程序的机器）定时去扫描处理，处理完把结果文件
写回去。这个页面只负责配置监听怎么跑、以及在真正开始跑之前调整一下谁先
谁后——实际的扫描/下架逻辑复用「运行」页那一套任务队列，不在这里重复。
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import accounts, remote_jobs
from temu_delisting.remote_config import (
    RemoteConfig,
    load_queue_order,
    load_remote_config,
    save_queue_order,
    save_remote_config,
)

_EXPLANATION = (
    "分机把任务请求放到共享文件夹里账号名称的子文件夹（子文件夹名字必须跟"
    "「账号管理」页里的显示名称完全一致），这台主机开启监听后会自动扫描处理，"
    "处理完把结果写回同一个文件夹。「远程扫描并自动下架」的任务会把这次扫描到"
    "的商品全部自动确认并直接执行下架，不需要人在这台主机上确认——"
    "如果不希望这样，分机那边就只提交「仅扫描」的任务。"
)

_ACTION_LABELS = {
    remote_jobs.ACTION_SCAN: "仅扫描",
    remote_jobs.ACTION_SCAN_AND_APPLY: "扫描并自动下架",
}
_QUEUE_COLUMNS = ["顺序", "账号", "操作", "日期范围", "提交时间"]
_QUEUE_REFRESH_INTERVAL_MS = 10000


class RemoteJobsSettingsWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._current_queue: list[remote_jobs.JobRequest] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        explanation = QLabel(_EXPLANATION)
        explanation.setWordWrap(True)
        explanation.setObjectName("hintLabel")
        layout.addWidget(explanation)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("共享文件夹路径："))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"例如：\\192.168.1.10\temu-jobs 或 D:\temu-jobs")
        folder_row.addWidget(self.folder_edit, stretch=1)
        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        self.enabled_checkbox = QCheckBox("开启监听（保存后立即生效）")
        layout.addWidget(self.enabled_checkbox)

        concurrency_row = QHBoxLayout()
        concurrency_row.addWidget(QLabel("同时最多处理几个远程任务："))
        self.concurrency_spin = QSpinBox()
        self.concurrency_spin.setRange(1, 10)
        self.concurrency_spin.setValue(1)
        concurrency_row.addWidget(self.concurrency_spin)
        concurrency_hint = QLabel("默认 1 = 一个一个排队跑；调大会同时开多个 Chrome 窗口，先用 1 观察效果再考虑调大")
        concurrency_hint.setObjectName("hintLabel")
        concurrency_row.addWidget(concurrency_hint, stretch=1)
        layout.addLayout(concurrency_row)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存设置")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._on_save)
        button_row.addWidget(save_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.status_label = QLabel("尚未保存设置。")
        self.status_label.setObjectName("hintLabel")
        layout.addWidget(self.status_label)

        layout.addWidget(self._build_queue_section())

        self._load_current()

        self._queue_timer = QTimer(self)
        self._queue_timer.timeout.connect(self._refresh_queue)
        self._queue_timer.start(_QUEUE_REFRESH_INTERVAL_MS)
        self._refresh_queue()

    # -- 共享文件夹 / 并发设置 ------------------------------------------------

    def _load_current(self) -> None:
        config = load_remote_config()
        self.folder_edit.setText(config.root_dir)
        self.enabled_checkbox.setChecked(config.enabled)
        self.concurrency_spin.setValue(config.max_concurrent_remote_jobs)
        self._refresh_status(config)

    def _refresh_status(self, config: RemoteConfig) -> None:
        if not config.root_dir:
            self.status_label.setText("还没有配置共享文件夹路径。")
        elif config.enabled:
            self.status_label.setText(f"监听已开启，共享文件夹：{config.root_dir}")
        else:
            self.status_label.setText(f"监听已关闭，共享文件夹：{config.root_dir}")

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择共享文件夹")
        if path:
            self.folder_edit.setText(path)

    def _on_save(self) -> None:
        root_dir = self.folder_edit.text().strip()
        enabled = self.enabled_checkbox.isChecked()
        if enabled and not root_dir:
            QMessageBox.warning(self, "保存设置", "开启监听前，请先填写共享文件夹路径。")
            return

        config = RemoteConfig(
            root_dir=root_dir, enabled=enabled, max_concurrent_remote_jobs=self.concurrency_spin.value()
        )
        save_remote_config(config)
        self._refresh_status(config)
        QMessageBox.information(self, "保存成功", "接口程序设置已保存。")

    # -- 排队清单 --------------------------------------------------------

    def _build_queue_section(self) -> QWidget:
        section = QWidget()
        layout = QVBoxLayout(section)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.setSpacing(8)

        header_row = QHBoxLayout()
        header_row.addWidget(QLabel("待处理的远程任务（按下面的顺序排队执行，可以用上移/下移调整）："))
        header_row.addStretch(1)
        self.move_up_button = QPushButton("上移")
        self.move_up_button.clicked.connect(self._on_move_up)
        self.move_down_button = QPushButton("下移")
        self.move_down_button.clicked.connect(self._on_move_down)
        refresh_button = QPushButton("刷新")
        refresh_button.clicked.connect(self._refresh_queue)
        header_row.addWidget(self.move_up_button)
        header_row.addWidget(self.move_down_button)
        header_row.addWidget(refresh_button)
        layout.addLayout(header_row)

        self.queue_table = QTableWidget(0, len(_QUEUE_COLUMNS))
        self.queue_table.setHorizontalHeaderLabels(_QUEUE_COLUMNS)
        self.queue_table.verticalHeader().setVisible(False)
        self.queue_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.queue_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.queue_table.setSelectionMode(QTableWidget.SingleSelection)
        self.queue_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        layout.addWidget(self.queue_table)

        return section

    def _refresh_queue(self) -> None:
        root_dir = self.folder_edit.text().strip()
        if not root_dir:
            self._current_queue = []
            self.queue_table.setRowCount(0)
            return

        account_names = [a.display_name for a in accounts.list_accounts()]
        try:
            pending = remote_jobs.scan_pending_requests(Path(root_dir), account_names)
        except OSError:
            return

        saved_order = load_queue_order()
        pruned_order = remote_jobs.prune_queue_order(saved_order, pending)
        if pruned_order != saved_order:
            save_queue_order(pruned_order)

        order_index = {job_id: i for i, job_id in enumerate(pruned_order)}
        self._current_queue = sorted(pending, key=lambda r: (order_index.get(r.job_id, len(pruned_order)), r.submitted_at))

        self.queue_table.setRowCount(len(self._current_queue))
        for row, request in enumerate(self._current_queue):
            values = [
                str(row + 1),
                request.account_name,
                _ACTION_LABELS.get(request.action, request.action),
                f"{request.start_date} ~ {request.end_date}",
                request.submitted_at[:19].replace("T", " "),
            ]
            for col, value in enumerate(values):
                self.queue_table.setItem(row, col, QTableWidgetItem(value))

    def _on_move_up(self) -> None:
        row = self.queue_table.currentRow()
        if row <= 0:
            return
        self._swap_queue_rows(row, row - 1)

    def _on_move_down(self) -> None:
        row = self.queue_table.currentRow()
        if row < 0 or row >= len(self._current_queue) - 1:
            return
        self._swap_queue_rows(row, row + 1)

    def _swap_queue_rows(self, i: int, j: int) -> None:
        self._current_queue[i], self._current_queue[j] = self._current_queue[j], self._current_queue[i]
        save_queue_order([request.job_id for request in self._current_queue])
        self._refresh_queue()
        self.queue_table.selectRow(j)
