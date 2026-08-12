"""复制登录信息新建账号：同一个 Temu 登录下如果挂了不止一个店铺，已经给
其中一个店铺建过账号、登录过之后，其余店铺不需要重新走"专属登录窗口"
流程——直接绑定到同一个 Chrome 配置目录（同一份真实登录态），只需要换
一下要绑定的店铺名字。任何一边刷新登录，两边自动一起生效（因为本来就是
同一个配置目录，不是各自的复制品）。
"""
from __future__ import annotations

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

from ..profile_sharing import resolve_shared_profile_id


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
            "已经给其中一个店铺登录过了。剩下的店铺不用重新走一遍登录窗口，直接绑定"
            "到同一份登录信息，只需要换一下要绑定的店铺名字。"
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

        try:
            profile_id = resolve_shared_profile_id(source_id)
        except ValueError as exc:
            QMessageBox.warning(self, "复制登录信息", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "复制登录信息", f"迁移来源账号的登录信息失败：{exc}")
            return

        account = accounts.create_account(display_name, mall_name=mall_name, profile_id=profile_id)
        self.created_account = account
        self.accept()
