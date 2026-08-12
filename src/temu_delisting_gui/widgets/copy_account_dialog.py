"""复制登录信息新建账号：同一个 Temu 登录下如果挂了不止一个店铺，已经给
其中一个店铺建过账号、导入过 Cookie 之后，其余店铺不需要重新走一遍
Cookie-Editor 导出/粘贴流程——反正背后是同一份登录 Cookie，重新导一次
纯属多余步骤，直接从已有账号复制登录态文件，只需要换一下要绑定的
店铺名字。
"""
from __future__ import annotations

import shutil

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from temu_delisting import accounts


class CopyAccountDialog(QDialog):
    def __init__(self, source_accounts: list[accounts.Account], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("复制登录信息新建账号")
        self.setMinimumWidth(460)

        self.created_account: accounts.Account | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        hint = QLabel(
            "适用场景：同一个 Temu 登录下有多个店铺（切换店铺弹窗里能看到好几个），"
            "已经给其中一个店铺建过账号了。剩下的店铺不用重新导出 Cookie，直接从这个"
            "账号复制登录信息，只需要换一下要绑定的店铺名字。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        source_row = QHBoxLayout()
        source_row.addWidget(QLabel("从哪个账号复制登录信息："))
        self.source_combo = QComboBox()
        for account in source_accounts:
            self.source_combo.addItem(account.display_name, userData=account.id)
        source_row.addWidget(self.source_combo, stretch=1)
        layout.addLayout(source_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("新账号/店铺名称："))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：Dwmane Shop")
        name_row.addWidget(self.name_input, stretch=1)
        layout.addLayout(name_row)

        mall_row = QHBoxLayout()
        mall_row.addWidget(QLabel("自动切换的店铺名称："))
        self.mall_input = QLineEdit()
        self.mall_input.setPlaceholderText("网页右上角显示的店铺名字，必须完全一致")
        mall_row.addWidget(self.mall_input, stretch=1)
        layout.addLayout(mall_row)

        mall_hint = QLabel("这里必须填——既然是同一登录下的多个店铺，不填的话程序没法知道每次该自动切到哪个店铺。")
        mall_hint.setObjectName("hintLabel")
        mall_hint.setWordWrap(True)
        layout.addWidget(mall_hint)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        self.finish_button = QPushButton("复制并创建")
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.clicked.connect(self._on_finish)
        button_row.addWidget(cancel_button)
        button_row.addWidget(self.finish_button)
        layout.addLayout(button_row)

    def _on_finish(self) -> None:
        display_name = self.name_input.text().strip()
        mall_name = self.mall_input.text().strip()
        source_id = self.source_combo.currentData()

        if not display_name:
            QMessageBox.warning(self, "复制登录信息", "请填新账号/店铺名称。")
            return
        if not mall_name:
            QMessageBox.warning(
                self,
                "复制登录信息",
                "店铺名称必须填——既然是同一登录下的多个店铺，不填的话程序没法知道"
                "每次该自动切到哪个店铺。",
            )
            return
        if not source_id:
            return

        source_paths = accounts.account_paths(source_id)
        if not source_paths.storage_state_path.exists():
            QMessageBox.warning(self, "复制登录信息", "选中的这个账号还没有登录信息，没法复制。")
            return

        account = accounts.create_account(display_name, mall_name=mall_name)
        target_paths = accounts.account_paths(account.id)
        shutil.copy(source_paths.storage_state_path, target_paths.storage_state_path)

        self.created_account = account
        self.accept()
