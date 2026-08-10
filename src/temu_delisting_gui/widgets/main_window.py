"""主窗口：账号选择器 + 日期范围 + 扫描/下架/停止按钮 + 进度条 + 实时日志区，
外加一个"审核清单"标签页。

扫描、下架都在各自的后台线程（ScanWorker/ApplyWorker）里跑，不卡界面；
扫描完成会自动切到审核清单页；下架支持中途"停止"（等当前商品处理完再停，
不会中途打断正在填的表单）。
"""
from __future__ import annotations

import threading

from PySide6.QtCore import QDate
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import accounts
from temu_delisting.config import load_settings
from temu_delisting.store import open_store

from .._version import __version__
from ..worker import ApplyWorker, ScanWorker
from .login_wizard import LoginWizardDialog
from .review_table import ReviewTableWidget


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"Temu 违规商品下架助手 v{__version__}")
        self.resize(960, 680)

        self._scan_worker: ScanWorker | None = None
        self._apply_worker: ApplyWorker | None = None
        self._stop_event: threading.Event | None = None
        self._current_batch_id: str | None = None

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
        layout.addWidget(self._build_progress_bar())
        layout.addWidget(self._build_log_panel(), stretch=1)
        return tab

    # -- 账号选择区 --------------------------------------------------

    def _build_account_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        label = QLabel("当前账号：")
        self.account_combo = QComboBox()
        self.account_combo.setMinimumWidth(220)

        self.add_account_button = QPushButton("+ 添加账号")
        self.add_account_button.clicked.connect(self._on_add_account_clicked)

        layout.addWidget(label)
        layout.addWidget(self.account_combo, stretch=1)
        layout.addWidget(self.add_account_button)
        return layout

    def _reload_accounts(self) -> None:
        self.account_combo.clear()
        account_list = accounts.list_accounts()
        if not account_list:
            self.account_combo.addItem("尚未添加账号", userData=None)
            self.start_scan_button.setEnabled(False)
            return

        for account in account_list:
            self.account_combo.addItem(account.display_name, userData=account.id)
        self.start_scan_button.setEnabled(True)

    def _on_add_account_clicked(self) -> None:
        dialog = LoginWizardDialog(self)
        if dialog.exec() == LoginWizardDialog.Accepted and dialog.created_account is not None:
            self._reload_accounts()
            index = self.account_combo.findData(dialog.created_account.id)
            if index >= 0:
                self.account_combo.setCurrentIndex(index)
            self._log(f"【添加账号】已成功添加账号「{dialog.created_account.display_name}」。")

    # -- 日期范围 --------------------------------------------------------

    def _build_date_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()
        yesterday = QDate.currentDate().addDays(-1)

        layout.addWidget(QLabel("违规开始日期："))
        self.start_date_edit = QDateEdit(yesterday)
        self.start_date_edit.setCalendarPopup(True)
        self.start_date_edit.setDisplayFormat("yyyy-MM-dd")
        layout.addWidget(self.start_date_edit)

        layout.addWidget(QLabel("结束日期："))
        self.end_date_edit = QDateEdit(yesterday)
        self.end_date_edit.setCalendarPopup(True)
        self.end_date_edit.setDisplayFormat("yyyy-MM-dd")
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

        self.dry_run_checkbox = QCheckBox("仅测试（不会真正提交下架申请）")
        self.dry_run_checkbox.setChecked(True)

        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop_clicked)

        layout.addWidget(self.start_scan_button)
        layout.addWidget(self.start_apply_button)
        layout.addWidget(self.dry_run_checkbox)
        layout.addStretch(1)
        layout.addWidget(self.stop_button)
        return layout

    # -- 扫描 --------------------------------------------------------

    def _on_start_scan_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "开始扫描", "请先添加一个账号。")
            return

        start = self.start_date_edit.date().toString("yyyy-MM-dd")
        end = self.end_date_edit.date().toString("yyyy-MM-dd")
        if self.start_date_edit.date() > self.end_date_edit.date():
            QMessageBox.warning(self, "开始扫描", "开始日期不能晚于结束日期。")
            return

        settings = load_settings(account_id=account_id)

        self.start_scan_button.setEnabled(False)
        self.start_apply_button.setEnabled(False)
        self.add_account_button.setEnabled(False)
        self.progress_bar.setRange(0, 0)  # 不确定进度，先转圈
        self.progress_bar.setFormat("扫描中…")
        self.statusBar().showMessage("扫描中…")
        self._log(f"【开始扫描】账号「{self.account_combo.currentText()}」，日期 {start} ~ {end}")

        self._scan_worker = ScanWorker(settings, start, end)
        self._scan_worker.log_line.connect(self._log)
        self._scan_worker.finished_ok.connect(self._on_scan_finished)
        self._scan_worker.failed.connect(self._on_scan_failed)
        self._scan_worker.start()

    def _on_scan_finished(self, result) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setFormat(f"扫描完成，共 {result.row_count} 条")
        self.statusBar().showMessage("扫描完成")
        self.start_scan_button.setEnabled(True)
        self.add_account_button.setEnabled(True)

        self._current_batch_id = result.batch_id
        self.start_apply_button.setEnabled(True)

        account_id = self.account_combo.currentData()
        settings = load_settings(account_id=account_id)
        self.review_table.load(settings, result.batch_id, result.suggestions)
        self._tabs.setCurrentWidget(self.review_table)

    def _on_scan_failed(self, message: str) -> None:
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("扫描失败")
        self.statusBar().showMessage("扫描失败")
        self.start_scan_button.setEnabled(True)
        self.add_account_button.setEnabled(True)
        self._log(f"【扫描失败】{message}")
        QMessageBox.warning(self, "扫描失败", message)

    # -- 下架 --------------------------------------------------------

    def _on_start_apply_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        if not account_id:
            QMessageBox.information(self, "开始下架", "请先添加一个账号。")
            return
        if not self._current_batch_id:
            QMessageBox.information(self, "开始下架", "请先扫描一次，并在「审核清单」页保存审核结果。")
            return

        settings = load_settings(account_id=account_id)
        dry_run = self.dry_run_checkbox.isChecked()

        with open_store(settings.db_path) as store:
            confirmed_count = len(
                store.list_suggestions(self._current_batch_id, review_status="confirmed")
            )
        if confirmed_count == 0:
            QMessageBox.information(
                self, "开始下架", "这个批次没有已确认待下架的商品，请先在「审核清单」页确认并保存。"
            )
            return

        if not dry_run:
            reply = QMessageBox.question(
                self,
                "确认下架",
                f"即将对 {confirmed_count} 个已确认的商品执行真实下架申请，此操作不可撤销，确定继续吗？",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                return

        self.start_scan_button.setEnabled(False)
        self.start_apply_button.setEnabled(False)
        self.add_account_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.progress_bar.setRange(0, confirmed_count)
        self.progress_bar.setValue(0)
        self.progress_bar.setFormat("准备开始…")
        self.statusBar().showMessage("下架处理中…")
        self._log(
            f"【开始下架】批次 {self._current_batch_id}，共 {confirmed_count} 个商品"
            f"{'（仅测试，不会真正提交）' if dry_run else ''}"
        )

        self._stop_event = threading.Event()
        self._apply_worker = ApplyWorker(
            settings, self._current_batch_id, dry_run, self._stop_event.is_set
        )
        self._apply_worker.log_line.connect(self._log)
        self._apply_worker.progress_changed.connect(self._on_apply_progress)
        self._apply_worker.finished_ok.connect(self._on_apply_finished)
        self._apply_worker.failed.connect(self._on_apply_failed)
        self._apply_worker.start()

    def _on_apply_progress(self, current: int, total: int, spu_id: str) -> None:
        self.progress_bar.setValue(current)
        self.progress_bar.setFormat(f"处理中 {current}/{total}：SPU {spu_id}")

    def _on_apply_finished(self, result) -> None:
        self.stop_button.setEnabled(False)
        self.start_scan_button.setEnabled(True)
        self.start_apply_button.setEnabled(True)
        self.add_account_button.setEnabled(True)
        self.statusBar().showMessage("下架处理完成" if not result.stopped_early else "已停止")

        outcomes = result.all_skc_outcomes
        success = sum(1 for o in outcomes if o.status == "success")
        needs_follow_up = sum(1 for o in outcomes if o.status != "success")
        failed_spu_count = len(result.failed_spus)

        self.progress_bar.setFormat(
            f"{'已停止' if result.stopped_early else '处理完成'}：成功 {success}，需人工跟进 {needs_follow_up}"
        )

        summary_lines = [
            f"批次：{self._current_batch_id}",
            f"SPU 整体处理成功：{len(result.spu_results) - failed_spu_count}",
            f"SPU 整体处理失败：{failed_spu_count}",
            f"SKC 下架成功：{success}",
            f"SKC 需要人工跟进（失败/超时）：{needs_follow_up}",
        ]
        if result.stopped_early:
            summary_lines.append("（已手动停止，还有商品没处理完）")
        self._log("【下架完成】" + "；".join(summary_lines))

        QMessageBox.information(self, "下架处理完成", "\n".join(summary_lines))

    def _on_apply_failed(self, message: str) -> None:
        self.stop_button.setEnabled(False)
        self.start_scan_button.setEnabled(True)
        self.start_apply_button.setEnabled(True)
        self.add_account_button.setEnabled(True)
        self.progress_bar.setFormat("下架失败")
        self.statusBar().showMessage("下架失败")
        self._log(f"【下架失败】{message}")
        QMessageBox.warning(self, "下架失败", message)

    def _on_stop_clicked(self) -> None:
        if self._stop_event is not None and self._apply_worker is not None:
            self._stop_event.set()
            self.stop_button.setEnabled(False)
            self._log("【停止】已收到停止请求，会在当前商品处理完后停下来（不会中途打断正在提交的表单）。")
        else:
            self._log("【停止】当前没有正在执行的下架任务。")

    # -- 进度条 --------------------------------------------------------

    def _build_progress_bar(self) -> QProgressBar:
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat("等待开始")
        return self.progress_bar

    # -- 日志区 --------------------------------------------------------

    def _build_log_panel(self) -> QPlainTextEdit:
        self.log_panel = QPlainTextEdit()
        self.log_panel.setObjectName("logPanel")
        self.log_panel.setReadOnly(True)
        self._log("欢迎使用 Temu 违规商品下架助手。")
        return self.log_panel

    def _log(self, message: str) -> None:
        self.log_panel.appendPlainText(message)
