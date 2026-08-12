"""编辑账号：改显示名称、设置/修改这个账号绑定的店铺名称（自动切换用）。

同一个 Temu 登录下可能挂了不止一个店铺，网站自己记的"当前激活的是哪个
店铺"是服务端会话状态，光靠 Cookie 不能保证自动化落地就在正确的店铺上，
所以每个账号需要单独告诉程序它对应网页上显示的哪个店铺名字。只有一个
店铺的话，这里留空就行（不会做任何校验/切换）。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class EditAccountDialog(QDialog):
    def __init__(self, display_name: str, mall_name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("编辑账号")
        self.setMinimumWidth(420)

        self.new_display_name = display_name
        self.new_mall_name = mall_name

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("账号/店铺名称："))
        self.name_input = QLineEdit(display_name)
        name_row.addWidget(self.name_input, stretch=1)
        layout.addLayout(name_row)

        mall_row = QHBoxLayout()
        mall_row.addWidget(QLabel("自动切换的店铺名称："))
        self.mall_input = QLineEdit(mall_name)
        self.mall_input.setPlaceholderText("留空表示不需要自动切换店铺")
        mall_row.addWidget(self.mall_input, stretch=1)
        layout.addLayout(mall_row)

        hint = QLabel(
            "如果这个登录下有多个店铺，这里要填网页右上角显示的店铺名字（必须完全"
            "一致），程序每次运行前会自动切到这个店铺；只有一个店铺的话留空就行。"
        )
        hint.setObjectName("hintLabel")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        save_button = QPushButton("保存")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._on_save)
        button_row.addWidget(cancel_button)
        button_row.addWidget(save_button)
        layout.addLayout(button_row)

    def _on_save(self) -> None:
        name = self.name_input.text().strip()
        if not name:
            return
        self.new_display_name = name
        self.new_mall_name = self.mall_input.text().strip()
        self.accept()
