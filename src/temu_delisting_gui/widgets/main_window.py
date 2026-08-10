"""主窗口：账号选择器 + 开始扫描/停止按钮 + 进度条 + 实时日志区。

Stage 2 只搭骨架，不接真实的自动化逻辑——按钮点了会在日志区打印一行提示，
后续阶段再把 actions.run_scan / run_apply 真正接上。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import accounts

from .login_wizard import LoginWizardDialog


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Temu 违规商品下架助手")
        self.resize(880, 620)

        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        root_layout.addLayout(self._build_account_row())
        root_layout.addLayout(self._build_action_row())
        root_layout.addWidget(self._build_progress_bar())
        root_layout.addWidget(self._build_log_panel(), stretch=1)

        self.statusBar().showMessage("就绪")

        self._reload_accounts()

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

    # -- 操作区 --------------------------------------------------------

    def _build_action_row(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.start_scan_button = QPushButton("开始扫描")
        self.start_scan_button.setObjectName("primaryButton")
        self.start_scan_button.clicked.connect(self._on_start_scan_clicked)

        self.stop_button = QPushButton("停止")
        self.stop_button.setObjectName("dangerButton")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self._on_stop_clicked)

        layout.addWidget(self.start_scan_button)
        layout.addWidget(self.stop_button)
        layout.addStretch(1)
        return layout

    def _on_start_scan_clicked(self) -> None:
        account_id = self.account_combo.currentData()
        account_name = self.account_combo.currentText()
        self._log(
            f"【开始扫描】账号「{account_name}」（{account_id}）—— "
            f"扫描/审核/下架流程将在后续阶段接入。"
        )

    def _on_stop_clicked(self) -> None:
        self._log("【停止】收到停止请求（占位，尚未接入真实任务）。")

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
