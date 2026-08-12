"""登录向导："专属登录窗口"方案——点按钮弹出一个真实的、系统直接启动的
Chrome 窗口（完全不经过 Playwright/CDP），在里面跟平时一样正常登录，
不用再导出/粘贴 Cookie。

流程：
1.（新建账号才需要）起一个账号/店铺名称，选填店铺名称
2. 点"打开专属登录窗口"，在弹出的真实 Chrome 窗口里正常登录
3. 登录完成后回来点"完成"，保存

已有账号第一次用这个流程时，如果之前是走 Cookie-Editor 那一套（有
storage_state.json），会自动把旧登录信息迁移进新建的 Chrome 配置目录，
不用重新登录一次。
"""
from __future__ import annotations

import uuid

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
from temu_delisting.browser import migrate_storage_state_into_profile
from temu_delisting.chrome_profile import open_login_window
from temu_delisting.config import load_settings

from ..profile_sharing import account_has_login, resolve_shared_profile_id


class LoginWizardDialog(QDialog):
    def __init__(self, parent=None, existing_account: accounts.Account | None = None) -> None:
        """existing_account 传了就是"更新登录信息"模式：不新建账号，只重新
        打开这个账号绑定的专属登录窗口，账号名字/店铺名称都不在这里改。"""
        super().__init__(parent)
        self._existing_account = existing_account
        self._profile_id = existing_account.profile_id if existing_account else ""
        self._login_window_opened = False

        self.setWindowTitle("更新登录信息" if existing_account else "添加账号")
        self.setMinimumWidth(480)

        self.created_account: accounts.Account | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        if existing_account is None:
            layout.addLayout(self._build_name_row())
            layout.addLayout(self._build_mall_name_row())
        else:
            title = QLabel(f"正在为账号「{existing_account.display_name}」更新登录信息")
            title.setObjectName("sectionTitle")
            layout.addWidget(title)

            share_section = self._build_share_section(existing_account)
            if share_section is not None:
                layout.addLayout(share_section)
                divider = self._hint_label("——或者，重新走一遍登录流程——")
                layout.addWidget(divider)

        hint = self._hint_label(
            "点下面的按钮会打开一个独立的、真实的 Chrome 窗口（不是自动化窗口，"
            "跟你平时用的浏览器一样），在里面正常登录 Temu 卖家中心。登录完成后"
            "把那个窗口关掉，回到这里点「完成」。"
        )
        layout.addWidget(hint)

        self.open_button = QPushButton("打开专属登录窗口")
        self.open_button.setObjectName("primaryButton")
        self.open_button.clicked.connect(self._on_open_login_window)
        layout.addWidget(self.open_button)

        self.status_label = self._hint_label("尚未打开登录窗口")
        layout.addWidget(self.status_label)

        layout.addLayout(self._build_bottom_row())

    # -- 小工具 ----------------------------------------------------------

    def _hint_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("hintLabel")
        label.setWordWrap(True)
        return label

    # -- 各行 UI ----------------------------------------------------------

    def _build_name_row(self):
        layout = QHBoxLayout()
        layout.addWidget(QLabel("账号/店铺名称："))
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：SaveNest 美国站")
        layout.addWidget(self.name_input, stretch=1)
        return layout

    def _build_mall_name_row(self):
        layout = QHBoxLayout()
        layout.addWidget(QLabel("店铺名称（一个登录下有多个店铺才需要填）："))
        self.mall_name_input = QLineEdit()
        self.mall_name_input.setPlaceholderText("留空表示不需要自动切换店铺")
        layout.addWidget(self.mall_name_input, stretch=1)
        return layout

    def _build_share_section(self, existing_account: accounts.Account):
        """如果这个账号跟别的账号本来就是同一个 Temu 登录（比如同一个手机号
        底下的另一个店铺，导入 Excel 时建的），不需要在这里重新走一遍手动
        登录——直接绑定到那个账号已经配置好的登录信息就行，跟"复制账号"
        是同一套逻辑，只是这次是给已经存在的账号"补"登录信息，不是新建。
        没有别的已登录账号可选时，这个区块不显示。"""
        candidates = [
            a for a in accounts.list_accounts() if a.id != existing_account.id and account_has_login(a)
        ]
        if not candidates:
            return None

        layout = QHBoxLayout()
        layout.addWidget(QLabel("共用已登录账号的登录信息："))
        self.share_combo = QComboBox()
        for account in candidates:
            self.share_combo.addItem(account.display_name, userData=account.id)
        layout.addWidget(self.share_combo, stretch=1)

        share_button = QPushButton("绑定")
        share_button.clicked.connect(self._on_share_clicked)
        layout.addWidget(share_button)
        return layout

    def _on_share_clicked(self) -> None:
        source_id = self.share_combo.currentData()
        if not source_id or self._existing_account is None:
            return

        try:
            profile_id = resolve_shared_profile_id(source_id)
        except ValueError as exc:
            QMessageBox.warning(self, "共用登录信息", str(exc))
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "共用登录信息", f"迁移来源账号的登录信息失败：{exc}")
            return

        accounts.set_profile_id(self._existing_account.id, profile_id)
        self.created_account = self._existing_account
        self.accept()

    def _build_bottom_row(self):
        layout = QHBoxLayout()
        layout.addStretch(1)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)

        self.finish_button = QPushButton("完成")
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self._on_finish)

        layout.addWidget(cancel_button)
        layout.addWidget(self.finish_button)
        return layout

    # -- 逻辑 ----------------------------------------------------------

    def _on_open_login_window(self) -> None:
        if not self._profile_id:
            self._profile_id = uuid.uuid4().hex
            if self._existing_account is not None:
                # 老账号第一次切到新方案：把原来的 storage_state.json 灌进
                # 新建的配置目录，避免"换个方案就要重新登录一次"。
                settings = load_settings(account_id=self._existing_account.id)
                profile_dir = accounts.chrome_profile_dir(self._profile_id)
                try:
                    migrate_storage_state_into_profile(
                        settings.storage_state_path, profile_dir, settings
                    )
                    self.status_label.setText("已把原有登录信息迁移进新配置，正在打开登录窗口…")
                except Exception as exc:  # noqa: BLE001
                    self.status_label.setText(f"迁移旧登录信息时出了点问题（不影响继续登录）：{exc}")

        profile_dir = accounts.chrome_profile_dir(self._profile_id)
        try:
            open_login_window(profile_dir)
        except RuntimeError as exc:
            QMessageBox.warning(self, "打开登录窗口失败", str(exc))
            return

        self._login_window_opened = True
        self.status_label.setText("登录窗口已打开——请在那个窗口里完成登录，完成后回来点「完成」。")
        self.finish_button.setEnabled(True)

    def _on_finish(self) -> None:
        if not self._login_window_opened:
            return

        if self._existing_account is not None:
            accounts.set_profile_id(self._existing_account.id, self._profile_id)
            self.created_account = self._existing_account
            self.accept()
            return

        display_name = self.name_input.text().strip()
        if not display_name:
            QMessageBox.warning(self, "添加账号", "请填账号/店铺名称。")
            return

        mall_name = self.mall_name_input.text().strip()
        account = accounts.create_account(display_name, mall_name=mall_name, profile_id=self._profile_id)
        self.created_account = account
        self.accept()
