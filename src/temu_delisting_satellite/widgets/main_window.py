"""分机端界面：往共享文件夹里丢任务请求，定时回来看结果。

这台机器不装完整的下架工具（不需要 Playwright、不需要登录 Temu），只负责
把"要处理哪个账号、哪段日期、要不要连自动下架一起做"写成一个请求文件放到
共享文件夹里对应账号的子文件夹下，剩下的事情全部由主机那边的程序完成。
"""
from __future__ import annotations

import platform
import uuid
from pathlib import Path

from datetime import datetime

from PySide6.QtCore import QDate, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import remote_jobs

from .._version import __version__
from ..config import SatelliteConfig, SubmittedJob, load_config, load_job_history, save_config, save_job_history

_ACTION_LABELS = {
    remote_jobs.ACTION_SCAN: "仅扫描（结果在主机那边人工确认后再下架）",
    remote_jobs.ACTION_SCAN_AND_APPLY: "扫描并自动下架（不需要人工确认，跑完直接下架，不可撤销）",
}
_HISTORY_COLUMNS = ["提交时间", "账号", "操作", "日期范围", "状态", "结果"]
_POLL_INTERVAL_MS = 5000


def _format_summary(result: dict) -> str:
    if result.get("status") == "failed":
        return f"失败：{result.get('message', '未知原因')}"

    parts = []
    if result.get("raw_row_count") is not None:
        parts.append(f"抓取 {result['raw_row_count']} 条")
    if result.get("unique_spu_count") is not None:
        parts.append(f"{result['unique_spu_count']} 个不同 SPU")
    if result.get("skc_success") is not None:
        parts.append(f"下架成功 {result['skc_success']}")
    if result.get("skc_needs_follow_up") is not None:
        parts.append(f"需人工跟进 {result['skc_needs_follow_up']}")
    if result.get("note"):
        parts.append(result["note"])
    return "，".join(parts) if parts else "已完成"


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Temu 下架任务提交端 v{__version__}")
        self.resize(760, 620)

        self._jobs: list[SubmittedJob] = load_job_history()

        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        explanation = QLabel(
            "这台机器不需要登录 Temu，只负责把任务请求丢到共享文件夹里，"
            "实际的扫描/下架由主机那台机器完成。「账号」下拉框里的名字必须跟"
            "主机「账号管理」页里的显示名称完全一致——共享文件夹里已经建好的"
            "账号子文件夹会自动列在下面，直接选就不会打错字。"
        )
        explanation.setWordWrap(True)
        explanation.setObjectName("hintLabel")
        layout.addWidget(explanation)

        layout.addLayout(self._build_folder_row())
        layout.addLayout(self._build_account_row())
        layout.addLayout(self._build_date_row())
        layout.addLayout(self._build_action_row())
        layout.addLayout(self._build_submit_row())
        layout.addWidget(self._build_history_table(), stretch=1)

        self._load_saved_config()
        self._refresh_account_list()
        self._render_history_table()

        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_results)
        self._poll_timer.start(_POLL_INTERVAL_MS)
        self._poll_results()

        self.statusBar().showMessage("就绪")

    # -- 共享文件夹 --------------------------------------------------------

    def _build_folder_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("共享文件夹路径："))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"例如：\\192.168.1.10\temu-jobs")
        self.folder_edit.editingFinished.connect(self._on_folder_changed)
        layout.addWidget(self.folder_edit, stretch=1)

        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._on_browse)
        layout.addWidget(browse_button)
        return layout

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择共享文件夹")
        if path:
            self.folder_edit.setText(path)
            self._on_folder_changed()

    def _on_folder_changed(self) -> None:
        self._save_current_config()
        self._refresh_account_list()

    # -- 账号 --------------------------------------------------------------

    def _build_account_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("账号："))
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)
        layout.addWidget(self.account_combo, stretch=1)

        refresh_button = QPushButton("刷新账号列表")
        refresh_button.clicked.connect(self._refresh_account_list)
        layout.addWidget(refresh_button)
        return layout

    def _refresh_account_list(self) -> None:
        root_dir = self.folder_edit.text().strip()
        preferred = self.account_combo.currentText() or load_config().last_account_name
        self.account_combo.clear()

        if not root_dir:
            return
        try:
            names = remote_jobs.list_account_folders(Path(root_dir))
        except OSError:
            names = []

        if not names:
            return
        self.account_combo.addItems(names)
        index = self.account_combo.findText(preferred)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)

    # -- 日期范围 ------------------------------------------------------------

    def _build_date_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        yesterday = QDate.currentDate().addDays(-1)

        layout.addWidget(QLabel("违规开始日期："))
        self.start_date_edit = QDateEdit(yesterday)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.start_date_edit.setMinimumWidth(130)
        layout.addWidget(self.start_date_edit)

        layout.addWidget(QLabel("结束日期："))
        self.end_date_edit = QDateEdit(yesterday)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
        self.end_date_edit.setMinimumWidth(130)
        layout.addWidget(self.end_date_edit)

        layout.addStretch(1)
        return layout

    # -- 操作类型 ------------------------------------------------------------

    def _build_action_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        layout.addWidget(QLabel("操作类型："))
        self.action_combo = QComboBox()
        for action, label in _ACTION_LABELS.items():
            self.action_combo.addItem(label, userData=action)
        layout.addWidget(self.action_combo, stretch=1)
        return layout

    # -- 提交 ----------------------------------------------------------------

    def _build_submit_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        self.submit_button = QPushButton("提交任务")
        self.submit_button.setObjectName("primaryButton")
        self.submit_button.clicked.connect(self._on_submit_clicked)
        layout.addWidget(self.submit_button)
        layout.addStretch(1)
        return layout

    def _on_submit_clicked(self) -> None:
        root_dir = self.folder_edit.text().strip()
        if not root_dir:
            QMessageBox.warning(self, "提交任务", "请先填写共享文件夹路径。")
            return
        root_path = Path(root_dir)
        if not root_path.exists():
            QMessageBox.warning(
                self, "提交任务", f"共享文件夹不存在或者访问不到：\n{root_dir}\n请检查网络连接和路径是否正确。"
            )
            return

        account_name = self.account_combo.currentText().strip()
        if not account_name:
            QMessageBox.warning(self, "提交任务", "请先选择账号（如果下拉框是空的，先点「刷新账号列表」）。")
            return

        if self.start_date_edit.date() > self.end_date_edit.date():
            QMessageBox.warning(self, "提交任务", "开始日期不能晚于结束日期。")
            return
        start = self.start_date_edit.date().toString("yyyy-MM-dd")
        end = self.end_date_edit.date().toString("yyyy-MM-dd")

        action = self.action_combo.currentData()
        if action == remote_jobs.ACTION_SCAN_AND_APPLY:
            reply = QMessageBox.question(
                self,
                "确认提交",
                f"即将对账号「{account_name}」提交「扫描并自动下架」任务，"
                "主机那边不会有人工确认，跑完会直接对违规商品执行真实下架申请，此操作不可撤销。\n\n"
                "确定要提交吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        job_id = uuid.uuid4().hex
        try:
            remote_jobs.write_request(
                root_path, account_name, job_id, action, start, end, submitted_by=platform.node()
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "提交失败", f"写入共享文件夹失败：\n{exc}")
            return

        job = SubmittedJob(
            job_id=job_id,
            account_name=account_name,
            action=action,
            start_date=start,
            end_date=end,
            submitted_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            root_dir=root_dir,
        )
        self._jobs.insert(0, job)
        save_job_history(self._jobs)
        self._render_history_table()
        self._save_current_config(last_account_name=account_name)

        self.statusBar().showMessage(f"已提交：账号「{account_name}」，任务 {job_id}", 5000)

    # -- 任务历史 / 结果轮询 ---------------------------------------------------

    def _build_history_table(self) -> QTableWidget:
        self.history_table = QTableWidget(0, len(_HISTORY_COLUMNS))
        self.history_table.setHorizontalHeaderLabels(_HISTORY_COLUMNS)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.history_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.Stretch)
        return self.history_table

    def _render_history_table(self) -> None:
        self.history_table.setRowCount(len(self._jobs))
        for row, job in enumerate(self._jobs):
            status, summary = self._status_and_summary(job)
            values = [
                job.submitted_at,
                job.account_name,
                _ACTION_LABELS.get(job.action, job.action),
                f"{job.start_date} ~ {job.end_date}",
                status,
                summary,
            ]
            for col, value in enumerate(values):
                self.history_table.setItem(row, col, QTableWidgetItem(value))

    @staticmethod
    def _status_and_summary(job: SubmittedJob) -> tuple[str, str]:
        if job.result is None:
            return "等待中", ""
        if job.result.get("status") == "failed":
            return "失败", _format_summary(job.result)
        return "已完成", _format_summary(job.result)

    def _poll_results(self) -> None:
        changed = False
        for job in self._jobs:
            if job.result is not None or not job.root_dir:
                continue
            result = remote_jobs.read_result(Path(job.root_dir), job.account_name, job.job_id)
            if result is not None:
                job.result = result
                changed = True
        if changed:
            save_job_history(self._jobs)
            self._render_history_table()

    # -- 本地设置 --------------------------------------------------------------

    def _load_saved_config(self) -> None:
        config = load_config()
        self.folder_edit.setText(config.root_dir)

    def _save_current_config(self, last_account_name: str | None = None) -> None:
        config = load_config()
        config.root_dir = self.folder_edit.text().strip()
        if last_account_name is not None:
            config.last_account_name = last_account_name
        save_config(config)
