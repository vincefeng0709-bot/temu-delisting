"""主窗口：账号选择器 + 日期范围 + 扫描/下架/停止按钮 + 任务列表 + 实时日志区，
外加一个"审核清单"标签页。

支持多账号并发运行：切到另一个账号，可以在原来那个账号还在跑扫描/下架的
同时，给这个新账号也开一个任务——每个任务是独立的后台线程（ScanWorker/
ApplyWorker），各自开自己的浏览器窗口，互不影响。任务列表显示每个任务的
账号、类型、状态，下架类任务可以单独停止（只停这一个，不影响其他任务）。
同一个账号同时只能有一个任务在跑（避免同一份登录态/数据库被两边同时写）。

"审核清单"页只有一份，跟着当前选中的账号走——切账号会自动刷新成那个账号
最近一次扫描的结果（如果有的话）。
"""
from __future__ import annotations

import threading
import uuid
from dataclasses import dataclass
from functools import partial

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import accounts
from temu_delisting.config import load_settings
from temu_delisting.store import open_store

from .._version import __version__
from ..worker import ApplyWorker, ScanWorker
from .copy_account_dialog import CopyAccountDialog
from .edit_account_dialog import EditAccountDialog
from .log_viewer import LogViewerDialog
from .login_wizard import LoginWizardDialog
from .review_table import ReviewTableWidget

_TASK_COLUMNS = ["账号", "类型", "状态", "操作"]


@dataclass
class JobEntry:
    job_id: str
    account_id: str
    account_name: str
    kind: str  # "scan" | "apply"
    row: int
    stop_event: threading.Event | None = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Temu 违规商品下架助手 v{__version__}")
        self.resize(1000, 720)

        self._jobs: dict[str, JobEntry] = {}
        self._workers: dict[str, object] = {}  # job_id -> ScanWorker/ApplyWorker（保活用，防止被垃圾回收）
        self._batch_by_account: dict[str, str] = {}

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_run_tab(), "运行")
        self.review_table = ReviewTableWidget()
        tabs.addTab(self.review_table, "审核清单")
        self._tabs = tabs

        self.statusBar().showMessage("就绪")
        self._reload_accounts()

    # -- "运行" 标签页 ----------------------------------------------------

    def _build_run_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addLayout(self._build_account_row())
        layout.addLayout(self._build_date_row())
        layout.addLayout(self._build_action_row())
        layout.addWidget(self._build_task_list())
        layout.addWidget(self._build_log_panel(), stretch=1)
        return tab

    # -- 账号选择区 --------------------------------------------------

    def _build_account_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        label = QLabel("当前账号：")
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)
        self.account_combo.currentIndexChanged.connect(self._on_account_selection_changed)

        self.rename_account_button = QPushButton("编辑")
        self.rename_account_button.clicked.connect(self._on_rename_account_clicked)

        self.update_login_button = QPushButton("更新登录信息")
        self.update_login_button.clicked.connect(self._on_update_login_clicked)

        self.delete_account_button = QPushButton("删除")
        self.delete_account_button.setObjectName("dangerButton")
        self.delete_account_button.clicked.connect(self._on_delete_account_clicked)

        self.add_account_button = QPushButton("+ 添加账号")
        self.add_account_button.clicked.connect(self._on_add_account_clicked)

        self.copy_account_button = QPushButton("+ 复制账号")
        self.copy_account_button.clicked.connect(self._on_copy_account_clicked)

        self.view_log_button = QPushButton("查看日志")
        self.view_log_button.clicked.connect(self._on_view_log_clicked)

        layout.addWidget(label)
        layout.addWidget(self.account_combo, stretch=1)
        layout.addWidget(self.rename_account_button)
        layout.addWidget(self.update_login_button)
        layout.addWidget(self.delete_account_button)
        layout.addWidget(self.add_account_button)
        layout.addWidget(self.copy_account_button)
        layout.addWidget(self.view_log_button)
        return layout

    def _on_copy_account_clicked(self) -> None:
        existing = accounts.list_accounts()
        if not existing:
            QMessageBox.information(self, "复制登录信息", "还没有任何账号，请先用「+ 添加账号」建一个。")
            return
        dialog = CopyAccountDialog(existing, self)
        if dialog.exec() == CopyAccountDialog.Accepted and dialog.created_account is not None:
            self._reload_accounts()
            index = self.account_combo.findData(dialog.created_account.id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
            self._log(f"【复制账号】已成功创建账号「{dialog.created_account.display_name}」（复制自已有登录信息）。")

    def _on_account_selection_changed(self) -> None:
        self._update_action_buttons()
        self._refresh_review_view_for_current_account()

    def _refresh_review_view_for_current_account(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            return
        batch_id = self._batch_by_account.get(account_id)
        if not batch_id:
            return
        settings = load_settings(account_id=account_id)
        with open_store(settings.db_path) as store:
            suggestions = store.list_suggestions(batch_id)
        self.review_table.load(settings, batch_id, suggestions)

    def _on_update_login_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "更新登录信息", "请先添加一个账号。")
            return
        account = accounts.get_account(account_id)
        if account is None:
            return

        dialog = LoginWizardDialog(self, existing_account=account)
        if dialog.exec() == LoginWizardDialog.Accepted:
            self._log(f"【更新登录信息】账号「{account.display_name}」的登录信息已更新。")

    def _on_view_log_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "查看日志", "请先添加一个账号。")
            return
        settings = load_settings(account_id=account_id)
        dialog = LogViewerDialog(settings.log_dir, self)
        dialog.exec()

    def _reload_accounts(self) -> None:
        current_id = self.account_combo.currentData()
        self.account_combo.blockSignals(True)
        self.account_combo.clear()
        account_list = accounts.list_accounts()
        has_accounts = bool(account_list)

        if not has_accounts:
            self.account_combo.addItem("尚未添加账号", userData=None)
        else:
            for account in account_list:
                self.account_combo.addItem(account.display_name, userData=account.id)
            index = self.account_combo.findData(current_id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
        self.account_combo.blockSignals(False)

        self.rename_account_button.setEnabled(has_accounts)
        self.update_login_button.setEnabled(has_accounts)
        self.delete_account_button.setEnabled(has_accounts)
        self._update_action_buttons()

    def _on_add_account_clicked(self) -> None:
        dialog = LoginWizardDialog(self)
        if dialog.exec() == LoginWizardDialog.Accepted and dialog.created_account is not None:
            self._reload_accounts()
            index = self.account_combo.findData(dialog.created_account.id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
            self._log(f"【添加账号】已成功添加账号「{dialog.created_account.display_name}」。")

    def _on_rename_account_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            return
        account = accounts.get_account(account_id)
        if account is None:
            return

        dialog = EditAccountDialog(account.display_name, account.mall_name, self)
        if dialog.exec() != EditAccountDialog.Accepted:
            return

        if dialog.new_display_name != account.display_name:
            accounts.rename_account(account_id, dialog.new_display_name)
        if dialog.new_mall_name != account.mall_name:
            accounts.set_mall_name(account_id, dialog.new_mall_name)

        self._reload_accounts()
        index = self.account_combo.findData(account_id)
        if index >= 0:
            self.account_combo.setCurrentIndex(index)
        self._log(
            f"【编辑账号】「{account.display_name}」→「{dialog.new_display_name}」，"
            f"绑定店铺：「{dialog.new_mall_name or '（不自动切换）'}」"
        )

    def _on_delete_account_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            return
        display_name = self.account_combo.currentText()

        if self._account_has_active_job(account_id):
            QMessageBox.warning(
                self, "删除账号", f"账号「{display_name}」还有任务在运行，不能删除，请等它跑完。"
            )
            return

        reply = QMessageBox.question(
            self,
            "删除账号",
            f"确定要删除账号「{display_name}」吗？\n这会连同它的登录信息、历史记录一起删掉，不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        accounts.delete_account(account_id)
        self._batch_by_account.pop(account_id, None)
        self._reload_accounts()
        self._log(f"【删除账号】已删除「{display_name}」。")

    # -- 日期范围 --------------------------------------------------------

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

    # -- 操作区 --------------------------------------------------------

    def _build_action_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.start_scan_button = QPushButton("开始扫描")
        self.start_scan_button.setObjectName("primaryButton")
        self.start_scan_button.clicked.connect(self._on_start_scan_clicked)

        self.start_apply_button = QPushButton("开始下架")
        self.start_apply_button.setObjectName("primaryButton")
        self.start_apply_button.setEnabled(False)
        self.start_apply_button.clicked.connect(self._on_start_apply_clicked)

        layout.addWidget(self.start_scan_button)
        layout.addWidget(self.start_apply_button)
        layout.addStretch(1)
        return layout

    # -- 并发控制 --------------------------------------------------------

    def _account_has_active_job(self, account_id: str) -> bool:
        return any(job.account_id == account_id for job in self._jobs.values())

    def _update_action_buttons(self) -> None:
        account_id = self.account_combo.currentData()
        has_accounts = bool(accounts.list_accounts())
        busy = bool(account_id) and self._account_has_active_job(account_id)
        has_batch = bool(account_id) and account_id in self._batch_by_account

        self.start_scan_button.setEnabled(has_accounts and not busy)
        self.start_apply_button.setEnabled(has_accounts and not busy and has_batch)

    def _on_worker_log(self, account_name: str, message: str) -> None:
        self._log(f"[{account_name}] {message}")

    # -- 扫描 --------------------------------------------------------

    def _on_start_scan_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "开始扫描", "请先添加一个账号。")
            return
        if self._account_has_active_job(account_id):
            QMessageBox.information(self, "开始扫描", "这个账号已经有任务在运行了，请等它完成。")
            return

        start = self.start_date_edit.date().toString("yyyy-MM-dd")
        end = self.end_date_edit.date().toString("yyyy-MM-dd")
        if self.start_date_edit.date() > self.end_date_edit.date():
            QMessageBox.warning(self, "开始扫描", "开始日期不能晚于结束日期。")
            return

        account_name = self.account_combo.currentText()
        settings = load_settings(account_id=account_id)
        self._log(f"【开始扫描】账号「{account_name}」，日期 {start} ~ {end}")

        job_id = uuid.uuid4().hex
        row = self._add_task_row(account_name, "扫描")
        self._jobs[job_id] = JobEntry(job_id, account_id, account_name, "scan", row)

        worker = ScanWorker(settings, start, end)
        self._workers[job_id] = worker
        worker.log_line.connect(partial(self._on_worker_log, account_name))
        worker.finished_ok.connect(partial(self._on_scan_finished, job_id))
        worker.failed.connect(partial(self._on_scan_failed, job_id))
        worker.start()

        self._update_action_buttons()

    def _on_scan_finished(self, job_id: str, result) -> None:
        job = self._jobs.pop(job_id, None)
        self._workers.pop(job_id, None)
        if job is None:
            return

        self._set_task_status(job.row, f"完成，共 {result.row_count} 条")
        self._batch_by_account[job.account_id] = result.batch_id
        self._log(f"[{job.account_name}] 扫描完成，共 {result.row_count} 条")

        if self.account_combo.currentData() == job.account_id:
            settings = load_settings(account_id=job.account_id)
            self.review_table.load(settings, result.batch_id, result.suggestions)
            self._tabs.setCurrentWidget(self.review_table)

        self._update_action_buttons()

    def _on_scan_failed(self, job_id: str, message: str) -> None:
        job = self._jobs.pop(job_id, None)
        self._workers.pop(job_id, None)
        if job is None:
            return

        self._set_task_status(job.row, "失败")
        self._log(f"[{job.account_name}] 扫描失败：{message}")
        QMessageBox.warning(self, "扫描失败", f"账号「{job.account_name}」：\n{message}")
        self._update_action_buttons()

    # -- 下架 --------------------------------------------------------

    def _on_start_apply_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "开始下架", "请先添加一个账号。")
            return
        if self._account_has_active_job(account_id):
            QMessageBox.information(self, "开始下架", "这个账号已经有任务在运行了，请等它完成。")
            return
        batch_id = self._batch_by_account.get(account_id)
        if not batch_id:
            QMessageBox.information(self, "开始下架", "请先扫描一次，并在「审核清单」页保存审核结果。")
            return

        account_name = self.account_combo.currentText()
        settings = load_settings(account_id=account_id)

        with open_store(settings.db_path) as store:
            confirmed_count = len(store.list_suggestions(batch_id, review_status="confirmed"))
        if confirmed_count == 0:
            QMessageBox.information(
                self, "开始下架", "这个批次没有已确认待下架的商品，请先在「审核清单」页确认并保存。"
            )
            return

        reply = QMessageBox.question(
            self,
            "确认下架",
            f"即将对账号「{account_name}」的 {confirmed_count} 个已确认商品执行真实下架申请，"
            "此操作不可撤销，确定继续吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        self._log(f"【开始下架】账号「{account_name}」，批次 {batch_id}，共 {confirmed_count} 个商品")

        job_id = uuid.uuid4().hex
        row = self._add_task_row(account_name, "下架")
        stop_event = threading.Event()
        self._jobs[job_id] = JobEntry(job_id, account_id, account_name, "apply", row, stop_event)
        self._add_stop_button(row, job_id)

        worker = ApplyWorker(settings, batch_id, False, stop_event.is_set)
        self._workers[job_id] = worker
        worker.log_line.connect(partial(self._on_worker_log, account_name))
        worker.progress_changed.connect(partial(self._on_apply_progress, job_id))
        worker.finished_ok.connect(partial(self._on_apply_finished, job_id, batch_id))
        worker.failed.connect(partial(self._on_apply_failed, job_id))
        worker.start()

        self._update_action_buttons()

    def _on_apply_progress(self, job_id: str, current: int, total: int, spu_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None:
            return
        self._set_task_status(job.row, f"处理中 {current}/{total}：SPU {spu_id}")

    def _on_apply_finished(self, job_id: str, batch_id: str, result) -> None:
        job = self._jobs.pop(job_id, None)
        self._workers.pop(job_id, None)
        if job is None:
            return

        outcomes = result.all_skc_outcomes
        success = sum(1 for o in outcomes if o.status == "success")
        needs_follow_up = sum(1 for o in outcomes if o.status != "success")
        failed_spu_count = len(result.failed_spus)

        status_prefix = "已停止" if result.stopped_early else "处理完成"
        self._set_task_status(job.row, f"{status_prefix}：成功 {success}，需人工跟进 {needs_follow_up}")
        self._clear_stop_button(job.row)

        summary_lines = [
            f"账号：{job.account_name}",
            f"批次：{batch_id}",
            f"SPU 整体处理成功：{len(result.spu_results) - failed_spu_count}",
            f"SPU 整体处理失败：{failed_spu_count}",
            f"SKC 下架成功：{success}",
            f"SKC 需要人工跟进（失败/超时）：{needs_follow_up}",
        ]
        if result.stopped_early:
            summary_lines.append("（已手动停止，还有商品没处理完）")
        self._log("【下架完成】" + "；".join(summary_lines))

        QMessageBox.information(self, "下架处理完成", "\n".join(summary_lines))
        self._update_action_buttons()

    def _on_apply_failed(self, job_id: str, message: str) -> None:
        job = self._jobs.pop(job_id, None)
        self._workers.pop(job_id, None)
        if job is None:
            return

        self._set_task_status(job.row, "失败")
        self._clear_stop_button(job.row)
        self._log(f"[{job.account_name}] 下架失败：{message}")
        QMessageBox.warning(self, "下架失败", f"账号「{job.account_name}」：\n{message}")
        self._update_action_buttons()

    def _on_stop_job_clicked(self, job_id: str) -> None:
        job = self._jobs.get(job_id)
        if job is None or job.stop_event is None:
            return
        job.stop_event.set()
        self._set_task_status(job.row, "正在停止…")
        self._log(f"[{job.account_name}] 已收到停止请求，会在当前商品处理完后停下来（不会中途打断正在提交的表单）。")
        button = self.task_table.cellWidget(job.row, 3)
        if button is not None:
            button.setEnabled(False)

    # -- 任务列表 --------------------------------------------------------

    def _build_task_list(self) -> QTableWidget:
        self.task_table = QTableWidget(0, len(_TASK_COLUMNS))
        self.task_table.setHorizontalHeaderLabels(_TASK_COLUMNS)
        self.task_table.verticalHeader().setVisible(False)
        self.task_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.task_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.task_table.setMaximumHeight(160)
        return self.task_table

    def _add_task_row(self, account_name: str, kind_label: str) -> int:
        row = self.task_table.rowCount()
        self.task_table.insertRow(row)
        self.task_table.setItem(row, 0, QTableWidgetItem(account_name))
        self.task_table.setItem(row, 1, QTableWidgetItem(kind_label))
        self.task_table.setItem(row, 2, QTableWidgetItem("运行中"))
        self.task_table.scrollToBottom()
        return row

    def _set_task_status(self, row: int, status: str) -> None:
        item = self.task_table.item(row, 2)
        if item is not None:
            item.setText(status)

    def _add_stop_button(self, row: int, job_id: str) -> None:
        button = QPushButton("停止")
        button.setObjectName("dangerButton")
        button.clicked.connect(partial(self._on_stop_job_clicked, job_id))
        self.task_table.setCellWidget(row, 3, button)

    def _clear_stop_button(self, row: int) -> None:
        self.task_table.removeCellWidget(row, 3)

    # -- 日志区 --------------------------------------------------------

    def _build_log_panel(self) -> QPlainTextEdit:
        self.log_panel = QPlainTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self._log("欢迎使用 Temu 违规商品下架助手。")
        return self.log_panel

    def _log(self, message: str) -> None:
        self.log_panel.appendPlainText(message)
