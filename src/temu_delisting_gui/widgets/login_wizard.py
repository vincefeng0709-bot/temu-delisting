"""登录向导：全程点按钮/粘贴文本，不碰命令行、不碰文件路径。

流程（跟 README「首次登录」一节的人工步骤一一对应，只是从命令行搬进了
图形界面）：
1. 起一个账号/店铺名称
2. 点按钮打开登录页，在自己平时用的 Chrome 里正常登录
3. 点按钮打开 Cookie-Editor 安装页（如果还没装）
4. 从两个域名（seller.kuajingmaihuo.com / agentseller.temu.com）分别导出
   Cookie，粘贴进两个文本框，各自点"导入这一段"
5. 两段都导入成功后，点"完成并保存"才会真正创建账号、写入登录态——
   中途取消不会留下半成品账号
"""
from __future__ import annotations

import webbrowser

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)

from temu_delisting import accounts
from temu_delisting.session_import import (
    convert_cookie_editor_export_text,
    load_existing_storage_state,
    merge_cookie_states,
    write_storage_state,
)

SELLER_LOGIN_URL = "https://seller.kuajingmaihuo.com"
COOKIE_EDITOR_STORE_URL = (
    "https://chrome.google.com/webstore/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm"
)


class LoginWizardDialog(QDialog):
    def __init__(self, parent=None, existing_account: accounts.Account | None = None) -> None:
        """existing_account 传了就是"更新登录信息"模式：不新建账号，只把
        新导出的 Cookie 合并进这个已有账号的登录态文件，账号名字/店铺名称
        都不在这里改（改名走"编辑"那个对话框）。"""
        super().__init__(parent)
        self._existing_account = existing_account
        self.setWindowTitle("更新登录信息" if existing_account else "添加账号")
        self.setMinimumWidth(560)

        self._cookie_state_seller: dict | None = None
        self._cookie_state_agent: dict | None = None
        self.created_account: accounts.Account | None = None

        layout = QVBoxLayout(self)
        layout.setSpacing(14)

        if existing_account is None:
            layout.addLayout(self._build_name_row())
            layout.addLayout(self._build_mall_name_row())
        else:
            layout.addWidget(QLabel(f"正在为账号「{existing_account.display_name}」更新登录信息"))
        layout.addWidget(self._section_label("① 登录卖家中心"))
        layout.addLayout(self._build_open_login_row())
        layout.addWidget(self._section_label("② 安装 Cookie 导出工具（装过了可跳过）"))
        layout.addLayout(self._build_open_cookie_editor_row())
        layout.addWidget(self._section_label("③ 导出并粘贴登录信息（两个都要）"))
        layout.addLayout(
            self._build_paste_row(
                hint="从 seller.kuajingmaihuo.com 页面用 Cookie-Editor 导出，粘贴到这里：",
                on_import=self._on_import_seller,
                status_attr="seller_status_label",
                text_attr="seller_text_edit",
            )
        )
        layout.addLayout(
            self._build_paste_row(
                hint="进入实际控制台（agentseller.temu.com）后再导出一次，粘贴到这里：",
                on_import=self._on_import_agent,
                status_attr="agent_status_label",
                text_attr="agent_text_edit",
            )
        )

        layout.addLayout(self._build_bottom_row())

        if existing_account is None:
            self.name_input.textChanged.connect(self._update_finish_enabled)
        self._update_finish_enabled()

    # -- 小工具 ----------------------------------------------------------

    def _section_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("sectionTitle")
        return label

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
        layout = QVBoxLayout()
        row = QHBoxLayout()
        row.addWidget(QLabel("店铺名称（如果一个登录下有多个店铺才需要填）："))
        self.mall_name_input = QLineEdit()
        self.mall_name_input.setPlaceholderText("留空表示不需要自动切换店铺")
        row.addWidget(self.mall_name_input, stretch=1)
        layout.addLayout(row)
        layout.addWidget(
            self._hint_label(
                "一个 Temu 登录下如果挂了不止一个店铺，需要在这里填网页右上角显示的"
                "店铺名字（必须完全一致），程序才知道每次要自动切到哪个店铺。"
                "只有一个店铺的话留空就行。"
            )
        )
        return layout

    def _build_open_login_row(self):
        layout = QHBoxLayout()
        layout.addWidget(self._hint_label("在你平时正常使用的 Chrome 里登录，一路点进去直到看到控制台首页。"))
        open_button = QPushButton("打开登录页面")
        open_button.clicked.connect(lambda: webbrowser.open(SELLER_LOGIN_URL))
        layout.addWidget(open_button)
        return layout

    def _build_open_cookie_editor_row(self):
        layout = QHBoxLayout()
        layout.addWidget(self._hint_label("用来导出登录信息的浏览器扩展，只需要装一次。"))
        open_button = QPushButton("打开安装页")
        open_button.clicked.connect(lambda: webbrowser.open(COOKIE_EDITOR_STORE_URL))
        layout.addWidget(open_button)
        return layout

    def _build_paste_row(self, hint: str, on_import, status_attr: str, text_attr: str):
        layout = QVBoxLayout()
        layout.addWidget(self._hint_label(hint))

        row = QHBoxLayout()
        text_edit = QTextEdit()
        text_edit.setPlaceholderText("在 Cookie-Editor 里点 Export → Export as JSON，粘贴到这里")
        text_edit.setFixedHeight(70)
        setattr(self, text_attr, text_edit)

        import_button = QPushButton("导入这一段")
        import_button.clicked.connect(on_import)

        status_label = QLabel("尚未导入")
        status_label.setObjectName("hintLabel")
        setattr(self, status_attr, status_label)

        row.addWidget(text_edit, stretch=1)
        col = QVBoxLayout()
        col.addWidget(import_button)
        col.addWidget(status_label)
        row.addLayout(col)

        layout.addLayout(row)
        return layout

    def _build_bottom_row(self):
        layout = QHBoxLayout()
        layout.addStretch(1)

        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)

        self.finish_button = QPushButton("更新并保存" if self._existing_account else "完成并保存")
        self.finish_button.setObjectName("primaryButton")
        self.finish_button.clicked.connect(self._on_finish)

        layout.addWidget(cancel_button)
        layout.addWidget(self.finish_button)
        return layout

    # -- 逻辑 ----------------------------------------------------------

    def _on_import_seller(self) -> None:
        self._cookie_state_seller = self._try_convert(
            self.seller_text_edit.toPlainText(), self.seller_status_label
        )
        self._update_finish_enabled()

    def _on_import_agent(self) -> None:
        self._cookie_state_agent = self._try_convert(
            self.agent_text_edit.toPlainText(), self.agent_status_label
        )
        self._update_finish_enabled()

    def _try_convert(self, text: str, status_label: QLabel) -> dict | None:
        if not text.strip():
            status_label.setText("尚未导入")
            return None
        try:
            state = convert_cookie_editor_export_text(text)
        except ValueError as exc:
            status_label.setText("✗ 导入失败")
            QMessageBox.warning(self, "导入失败", str(exc))
            return None
        status_label.setText(f"✓ 已导入 {len(state['cookies'])} 条")
        return state

    def _update_finish_enabled(self) -> None:
        name_ready = self._existing_account is not None or bool(self.name_input.text().strip())
        ready = bool(
            name_ready
            and self._cookie_state_seller is not None
            and self._cookie_state_agent is not None
        )
        self.finish_button.setEnabled(ready)

    def _on_finish(self) -> None:
        if self._cookie_state_seller is None or self._cookie_state_agent is None:
            return

        merged_new = merge_cookie_states({"cookies": [], "origins": []}, self._cookie_state_seller)
        merged_new = merge_cookie_states(merged_new, self._cookie_state_agent)

        if self._existing_account is not None:
            # 更新模式：合并进这个已有账号现有的登录态文件，不新建账号、
            # 不动账号名字/店铺名称。
            paths = accounts.account_paths(self._existing_account.id)
            existing_state = load_existing_storage_state(paths.storage_state_path)
            merged = merge_cookie_states(existing_state, merged_new)
            write_storage_state(merged, paths.storage_state_path)
            self.created_account = self._existing_account
            self.accept()
            return

        display_name = self.name_input.text().strip()
        if not display_name:
            return

        mall_name = self.mall_name_input.text().strip()
        account = accounts.create_account(display_name, mall_name=mall_name)
        paths = accounts.account_paths(account.id)
        write_storage_state(merged_new, paths.storage_state_path)

        self.created_account = account
        self.accept()
