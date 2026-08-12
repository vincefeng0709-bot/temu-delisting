"""账号管理页：账号的增删改查、从 Excel 批量导入账号"架子"，都集中在这个
独立页面，"运行"页只留一个账号选择器，不再挤一整排管理按钮。
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from temu_delisting import accounts
from temu_delisting.account_import import IMPORT_FORMAT_HELP, parse_account_excel
from temu_delisting.config import load_settings

from .copy_account_dialog import CopyAccountDialog
from .edit_account_dialog import EditAccountDialog
from .log_viewer import LogViewerDialog
from .login_wizard import LoginWizardDialog

_COLUMNS = ["选择", "显示名称", "店铺名称", "备注", "登录状态", "创建时间"]
_CHECKBOX_COL = 0
_NAME_COL = 1


def _account_has_login(account: accounts.Account) -> bool:
    if account.profile_id:
        profile_dir = accounts.chrome_profile_dir(account.profile_id)
        if profile_dir.exists() and any(profile_dir.iterdir()):
            return True
    return accounts.account_paths(account.id).storage_state_path.exists()


class AccountManagementWidget(QWidget):
    accounts_changed = Signal()

    def __init__(self, is_account_busy: Callable[[str], bool], parent=None) -> None:
        super().__init__(parent)
        self._is_account_busy = is_account_busy
        self._checkboxes: dict[int, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        layout.addLayout(self._build_toolbar())

        self.table = QTableWidget(0, len(_COLUMNS))
        self.table.setHorizontalHeaderLabels(_COLUMNS)
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.table.itemSelectionChanged.connect(self._update_button_states)
        layout.addWidget(self.table, stretch=1)

        self.refresh()

    # -- 工具栏 ------------------------------------------------------

    def _build_toolbar(self) -> QHBoxLayout:
        layout = QHBoxLayout()

        self.add_button = QPushButton("+ 添加账号")
        self.add_button.setObjectName("primaryButton")
        self.add_button.clicked.connect(self._on_add_clicked)

        self.copy_button = QPushButton("+ 复制账号")
        self.copy_button.clicked.connect(self._on_copy_clicked)

        self.import_button = QPushButton("导入 Excel")
        self.import_button.clicked.connect(self._on_import_clicked)

        self.import_help_button = QPushButton("Excel 格式说明")
        self.import_help_button.clicked.connect(self._on_import_help_clicked)

        self.select_all_button = QPushButton("全选")
        self.select_all_button.clicked.connect(lambda: self._set_all_checked(True))

        self.select_none_button = QPushButton("取消全选")
        self.select_none_button.clicked.connect(lambda: self._set_all_checked(False))

        self.edit_button = QPushButton("编辑")
        self.edit_button.clicked.connect(self._on_edit_clicked)

        self.update_login_button = QPushButton("更新登录信息")
        self.update_login_button.clicked.connect(self._on_update_login_clicked)

        self.view_log_button = QPushButton("查看日志")
        self.view_log_button.clicked.connect(self._on_view_log_clicked)

        self.delete_button = QPushButton("删除所选")
        self.delete_button.setObjectName("dangerButton")
        self.delete_button.clicked.connect(self._on_delete_clicked)

        layout.addWidget(self.add_button)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.import_button)
        layout.addWidget(self.import_help_button)
        layout.addWidget(self.select_all_button)
        layout.addWidget(self.select_none_button)
        layout.addStretch(1)
        layout.addWidget(self.edit_button)
        layout.addWidget(self.update_login_button)
        layout.addWidget(self.view_log_button)
        layout.addWidget(self.delete_button)
        return layout

    def _update_button_states(self) -> None:
        has_selection = self._selected_account_id() is not None
        self.edit_button.setEnabled(has_selection)
        self.update_login_button.setEnabled(has_selection)
        self.view_log_button.setEnabled(has_selection)
        self.delete_button.setEnabled(bool(self._checked_account_ids()))

    def _selected_account_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows() if self.table.selectionModel() else []
        if not rows:
            return None
        item = self.table.item(rows[0].row(), _NAME_COL)
        return item.data(Qt.UserRole) if item is not None else None

    def _checked_account_ids(self) -> list[str]:
        ids = []
        for row, checkbox in self._checkboxes.items():
            if checkbox.isChecked():
                item = self.table.item(row, _NAME_COL)
                if item is not None:
                    ids.append(item.data(Qt.UserRole))
        return ids

    def _set_all_checked(self, checked: bool) -> None:
        for checkbox in self._checkboxes.values():
            checkbox.setChecked(checked)
        self._update_button_states()

    # -- 表格刷新 ------------------------------------------------------

    def refresh(self) -> None:
        selected_id = self._selected_account_id()
        self._checkboxes = {}

        account_list = accounts.list_accounts()
        self.table.setRowCount(len(account_list))
        for row, account in enumerate(account_list):
            checkbox = QCheckBox()
            checkbox.stateChanged.connect(self._update_button_states)
            self._checkboxes[row] = checkbox
            self.table.setCellWidget(row, _CHECKBOX_COL, checkbox)

            has_login = _account_has_login(account)
            values = [
                account.display_name,
                account.mall_name or "（不需要切换）",
                account.notes,
                "已登录" if has_login else "未登录",
                account.created_at[:19].replace("T", " "),
            ]
            for col_offset, value in enumerate(values, start=_NAME_COL):
                item = QTableWidgetItem(value)
                if col_offset == _NAME_COL:
                    item.setData(Qt.UserRole, account.id)
                self.table.setItem(row, col_offset, item)

        if selected_id:
            for row in range(self.table.rowCount()):
                if self.table.item(row, _NAME_COL).data(Qt.UserRole) == selected_id:
                    self.table.selectRow(row)
                    break

        self._update_button_states()

    # -- 增 ------------------------------------------------------

    def _on_add_clicked(self) -> None:
        dialog = LoginWizardDialog(self)
        if dialog.exec() == LoginWizardDialog.Accepted and dialog.created_account is not None:
            self.refresh()
            self.accounts_changed.emit()

    def _on_copy_clicked(self) -> None:
        existing = accounts.list_accounts()
        if not existing:
            QMessageBox.information(self, "复制登录信息", "还没有任何账号，请先用「+ 添加账号」建一个。")
            return
        dialog = CopyAccountDialog(existing, self)
        if dialog.exec() == CopyAccountDialog.Accepted and dialog.created_account is not None:
            self.refresh()
            self.accounts_changed.emit()

    def _on_import_help_clicked(self) -> None:
        QMessageBox.information(self, "Excel 格式说明", IMPORT_FORMAT_HELP)

    def _on_import_clicked(self) -> None:
        path_str, _ = QFileDialog.getOpenFileName(self, "导入账号清单", "", "Excel 文件 (*.xlsx)")
        if not path_str:
            return

        try:
            result = parse_account_excel(Path(path_str))
        except ValueError as exc:
            QMessageBox.warning(self, "导入失败", f"{exc}\n\n点工具栏「Excel 格式说明」可以看完整的列名要求。")
            return
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "导入失败", f"读取文件失败，请确认是合法的 Excel 文件：{exc}")
            return

        existing_names = {a.display_name for a in accounts.list_accounts()}
        created = 0
        skipped = 0
        for shop in result.shops:
            if shop.display_name in existing_names:
                skipped += 1
                continue
            accounts.create_account(shop.display_name, mall_name=shop.mall_name, notes=shop.notes)
            existing_names.add(shop.display_name)
            created += 1

        self.refresh()
        self.accounts_changed.emit()

        summary = [f"新建了 {created} 个账号"]
        if skipped:
            summary.append(f"跳过了 {skipped} 个（名字跟已有账号重复）")
        if result.issues:
            summary.append("")
            summary.append("以下几行有问题，请核对源文件：")
            summary.extend(f"第 {issue.row_number} 行：{issue.message}" for issue in result.issues)
        summary.append("")
        summary.append("这些账号目前都还没有登录信息，需要逐个用「+ 添加账号」或「+ 复制账号」补上。")
        QMessageBox.information(self, "导入完成", "\n".join(summary))

    # -- 改 ------------------------------------------------------

    def _on_edit_clicked(self) -> None:
        account_id = self._selected_account_id()
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

        self.refresh()
        self.accounts_changed.emit()

    def _on_update_login_clicked(self) -> None:
        account_id = self._selected_account_id()
        if not account_id:
            return
        account = accounts.get_account(account_id)
        if account is None:
            return

        dialog = LoginWizardDialog(self, existing_account=account)
        if dialog.exec() == LoginWizardDialog.Accepted:
            self.refresh()
            self.accounts_changed.emit()

    # -- 查 ------------------------------------------------------

    def _on_view_log_clicked(self) -> None:
        account_id = self._selected_account_id()
        if not account_id:
            return
        settings = load_settings(account_id=account_id)
        dialog = LogViewerDialog(settings.log_dir, self)
        dialog.exec()

    # -- 删 ------------------------------------------------------

    def _on_delete_clicked(self) -> None:
        account_ids = self._checked_account_ids()
        if not account_ids:
            return

        selected_accounts = [accounts.get_account(aid) for aid in account_ids]
        selected_accounts = [a for a in selected_accounts if a is not None]

        busy = [a for a in selected_accounts if self._is_account_busy(a.id)]
        if busy:
            names = "、".join(f"「{a.display_name}」" for a in busy)
            QMessageBox.warning(self, "删除账号", f"{names} 还有任务在运行，不能删除，请等它跑完后再试。")
            return

        names = "、".join(f"「{a.display_name}」" for a in selected_accounts)
        reply = QMessageBox.question(
            self,
            "删除账号",
            f"确定要删除 {len(selected_accounts)} 个账号吗：{names}\n"
            "这会连同它们的登录信息、历史记录一起删掉，不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 就算某一个删除失败（比如文件占用抛异常），也要接着删剩下的，最后
        # 无论如何都要刷新界面——不能因为中间一个失败就让整个操作卡住不动，
        # 那样界面看起来就是"点了删除但什么都没变"，正是同事反馈的问题。
        errors = []
        for account in selected_accounts:
            try:
                accounts.delete_account(account.id)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"「{account.display_name}」：{exc}")

        self.refresh()
        self.accounts_changed.emit()

        if errors:
            QMessageBox.warning(self, "部分删除失败", "以下账号删除失败：\n" + "\n".join(errors))
