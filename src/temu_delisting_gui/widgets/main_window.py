"""主窗口："运行"标签页（账号选择器 + 日期范围 + 扫描/下架/停止按钮 + 任务
列表 + 实时日志区）+ "账号管理"标签页 + "审核清单"标签页。

账号的增删改查、批量导入都在"账号管理"页（account_management.py）里，
这边只留一个账号下拉选择器，账号列表变了会通过 accounts_changed 信号通知
这里刷新下拉框。

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
from pathlib import Path

from PySide6.QtCore import QDate, QTimer
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

from temu_delisting import accounts, remote_jobs
from temu_delisting.config import load_settings
from temu_delisting.remote_config import load_queue_order, load_remote_config, save_queue_order
from temu_delisting.store import open_store

from .._version import __version__
from ..worker import ApplyWorker, ScanWorker
from .account_management import AccountManagementWidget
from .remote_jobs_settings import RemoteJobsSettingsWidget
from .review_table import ReviewTableWidget

_TASK_COLUMNS = ["账号", "类型", "状态", "操作"]
_REMOTE_POLL_INTERVAL_MS = 10000


@dataclass
class JobEntry:
    job_id: str
    account_id: str
    account_name: str
    kind: str  # "scan" | "apply"
    row: int
    stop_event: threading.Event | None = None
    # 这个任务如果是分机通过共享文件夹远程触发的，这里记录对应的请求信息，
    # 完成/失败之后要把结果写回共享文件夹；本地手动点按钮触发的任务这里是
    # None，走原来的弹窗确认流程。
    remote_request: remote_jobs.JobRequest | None = None


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Temu 违规商品下架助手 v{__version__}")
        self.resize(1000, 720)

        self._jobs: dict[str, JobEntry] = {}
        self._workers: dict[str, object] = {}  # job_id -> ScanWorker/ApplyWorker（保活用，防止被垃圾回收）
        self._batch_by_account: dict[str, str] = {}
        # 扫描完了、但还没在「审核清单」页被看过的账号——尤其是远程扫描，
        # 跑完不会抢焦点切标签页，不加个提醒的话，同事很容易忘了去看，
        # 还以为扫描没跑或者结果丢了。哪个账号的批次被看过一次就从这里摘掉。
        self._unreviewed_accounts: set[str] = set()

        tabs = QTabWidget()
        self.setCentralWidget(tabs)

        tabs.addTab(self._build_run_tab(), "运行")
        self.account_management = AccountManagementWidget(self._account_has_active_job)
        self.account_management.accounts_changed.connect(self._reload_accounts)
        tabs.addTab(self.account_management, "账号管理")
        self.review_table = ReviewTableWidget()
        self._review_tab_index = tabs.addTab(self.review_table, "审核清单")
        tabs.addTab(RemoteJobsSettingsWidget(), "接口程序")
        self._tabs = tabs

        self.statusBar().showMessage("就绪")
        self._reload_accounts()

        self._remote_timer = QTimer(self)
        self._remote_timer.timeout.connect(self._poll_remote_jobs)
        self._remote_timer.start(_REMOTE_POLL_INTERVAL_MS)

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

        hint = QLabel("账号的增删改查、批量导入在「账号管理」页")
        hint.setObjectName("hintLabel")

        layout.addWidget(label)
        layout.addWidget(self.account_combo, stretch=1)
        layout.addWidget(hint)
        return layout

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
            batch_info = store.get_batch(batch_id)
            unique_spu_count = store.count_unique_spu(batch_id)
        self.review_table.load(
            settings,
            batch_id,
            suggestions,
            total_from_page=batch_info.total_from_page if batch_info else None,
            raw_row_count=batch_info.raw_row_count if batch_info else None,
            unique_spu_count=unique_spu_count,
        )
        self._mark_account_reviewed(account_id)

    def _mark_account_reviewed(self, account_id: str) -> None:
        self._unreviewed_accounts.discard(account_id)
        self._update_review_tab_badge()

    def _update_review_tab_badge(self) -> None:
        count = len(self._unreviewed_accounts)
        label = f"审核清单（{count} 个账号待查看）" if count else "审核清单"
        self._tabs.setTabText(self._review_tab_index, label)

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

        self._update_action_buttons()

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
        self._start_scan_job(account_id, account_name, start, end)

    def _start_scan_job(
        self,
        account_id: str,
        account_name: str,
        start: str,
        end: str,
        remote_request: remote_jobs.JobRequest | None = None,
    ) -> None:
        settings = load_settings(account_id=account_id)
        prefix = "【远程扫描】" if remote_request is not None else "【开始扫描】"
        self._log(f"{prefix}账号「{account_name}」，日期 {start} ~ {end}")

        job_id = uuid.uuid4().hex
        kind_label = "远程扫描" if remote_request is not None else "扫描"
        row = self._add_task_row(account_name, kind_label)
        self._jobs[job_id] = JobEntry(
            job_id, account_id, account_name, "scan", row, remote_request=remote_request
        )

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
        self._unreviewed_accounts.add(job.account_id)
        self._update_review_tab_badge()

        if job.remote_request is None and self.account_combo.currentData() == job.account_id:
            settings = load_settings(account_id=job.account_id)
            self.review_table.load(
                settings,
                result.batch_id,
                result.suggestions,
                total_from_page=result.total_from_page,
                raw_row_count=result.row_count,
                unique_spu_count=result.unique_spu_count,
            )
            self._tabs.setCurrentWidget(self.review_table)
            self._mark_account_reviewed(job.account_id)

        if job.remote_request is not None:
            self._handle_remote_scan_finished(job, result)

        self._update_action_buttons()

    def _handle_remote_scan_finished(self, job: JobEntry, result) -> None:
        request = job.remote_request
        assert request is not None
        if request.action == remote_jobs.ACTION_SCAN:
            self._write_remote_result(
                request,
                "completed",
                total_from_page=result.total_from_page,
                raw_row_count=result.row_count,
                unique_spu_count=result.unique_spu_count,
            )
            return

        # scan_and_apply：分机已经明确要求不需要人工复核，主机这边把这批
        # 扫到的条目（不分是否「建议下架」）全部自动确认，确认完立刻下架。
        settings = load_settings(account_id=job.account_id)
        with open_store(settings.db_path) as store:
            confirmed_count = store.confirm_all_suggested(result.batch_id)

        if confirmed_count == 0:
            self._log(f"[{job.account_name}] 远程任务：这次扫描没有抓到任何商品，本次不执行下架。")
            self._write_remote_result(
                request,
                "completed",
                total_from_page=result.total_from_page,
                raw_row_count=result.row_count,
                unique_spu_count=result.unique_spu_count,
                confirmed_count=0,
                note="扫描结果为空，未执行下架",
            )
            return

        self._log(f"[{job.account_name}] 远程任务：已自动确认 {confirmed_count} 个商品，接下来自动下架。")
        self._start_apply_job(job.account_id, job.account_name, result.batch_id, remote_request=request)

    def _on_scan_failed(self, job_id: str, message: str) -> None:
        job = self._jobs.pop(job_id, None)
        self._workers.pop(job_id, None)
        if job is None:
            return

        self._set_task_status(job.row, "失败")
        self._log(f"[{job.account_name}] 扫描失败：{message}")
        if job.remote_request is not None:
            self._write_remote_result(job.remote_request, "failed", message=message)
        else:
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
        self._start_apply_job(account_id, account_name, batch_id)

    def _start_apply_job(
        self,
        account_id: str,
        account_name: str,
        batch_id: str,
        remote_request: remote_jobs.JobRequest | None = None,
    ) -> None:
        settings = load_settings(account_id=account_id)

        job_id = uuid.uuid4().hex
        kind_label = "远程下架" if remote_request is not None else "下架"
        row = self._add_task_row(account_name, kind_label)
        stop_event = threading.Event()
        self._jobs[job_id] = JobEntry(
            job_id, account_id, account_name, "apply", row, stop_event, remote_request=remote_request
        )
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

        if job.remote_request is not None:
            self._write_remote_result(
                job.remote_request,
                "completed",
                batch_id=batch_id,
                skc_success=success,
                skc_needs_follow_up=needs_follow_up,
                spu_failed=failed_spu_count,
                stopped_early=result.stopped_early,
            )
        else:
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
        if job.remote_request is not None:
            self._write_remote_result(job.remote_request, "failed", message=message)
        else:
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

    # -- 接口程序（远程任务）------------------------------------------------

    def _poll_remote_jobs(self) -> None:
        config = load_remote_config()
        if not config.enabled or not config.root_dir:
            return

        root_dir = Path(config.root_dir)
        account_names = [a.display_name for a in accounts.list_accounts()]
        try:
            pending = remote_jobs.scan_pending_requests(root_dir, account_names)
        except OSError as exc:
            self._log(f"[接口程序] 读取共享文件夹失败：{exc}")
            return

        saved_order = load_queue_order()
        pruned_order = remote_jobs.prune_queue_order(saved_order, pending)
        if pruned_order != saved_order:
            save_queue_order(pruned_order)

        # 「正忙」按账号名字算，不区分是本地手动跑的还是远程触发的——同一个
        # 账号同一时间只能有一个任务，不管是谁发起的。并发上限只限制「同时
        # 在跑的远程任务」这一类，不影响同事在「运行」页手动点的任务。
        running_remote_count = sum(1 for job in self._jobs.values() if job.remote_request is not None)
        available_slots = max(0, config.max_concurrent_remote_jobs - running_remote_count)
        busy_account_names = {job.account_name for job in self._jobs.values()}

        to_start = remote_jobs.select_next_jobs(pending, pruned_order, busy_account_names, available_slots)

        for request in to_start:
            account = accounts.get_account_by_name(request.account_name)
            if account is None:
                self._log(f"[接口程序] 找不到账号「{request.account_name}」，跳过任务 {request.job_id}")
                self._write_remote_result(
                    request, "failed", message="主机这边找不到这个账号，请检查账号管理页里的显示名称是否完全一致"
                )
                continue

            self._log(
                f"[接口程序] 收到远程任务：账号「{account.display_name}」，"
                f"{'扫描并自动下架' if request.action == remote_jobs.ACTION_SCAN_AND_APPLY else '仅扫描'}，"
                f"{request.start_date} ~ {request.end_date}"
            )
            self._start_scan_job(
                account.id, account.display_name, request.start_date, request.end_date, remote_request=request
            )

    def _write_remote_result(self, request: remote_jobs.JobRequest, status: str, **extra) -> None:
        account_name = request.request_path.parent.name
        root_dir = request.request_path.parent.parent
        try:
            remote_jobs.write_result(root_dir, account_name, request.job_id, {"status": status, **extra})
            self._log(f"[接口程序] 已写回结果：账号「{account_name}」，任务 {request.job_id}，状态 {status}")
        except OSError as exc:
            self._log(f"[接口程序] 写回结果失败（任务 {request.job_id}）：{exc}")

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
