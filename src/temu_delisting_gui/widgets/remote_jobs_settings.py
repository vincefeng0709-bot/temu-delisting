"""「接口程序」设置页：配置共享文件夹路径 + 开关。

分机（每个店铺一台的小机器）把任务请求文件丢进共享文件夹里对应账号的
子文件夹，这台主机（跑这个程序的机器）定时去扫描处理，处理完把结果文件
写回去。这个页面只负责配置监听的共享文件夹在哪、要不要开启——实际的
扫描/下架逻辑复用「运行」页那一套任务队列，不在这里重复。
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from temu_delisting.remote_config import RemoteConfig, load_remote_config, save_remote_config

_EXPLANATION = (
    "分机把任务请求放到共享文件夹里账号名称的子文件夹（子文件夹名字必须跟"
    "「账号管理」页里的显示名称完全一致），这台主机开启监听后会自动扫描处理，"
    "处理完把结果写回同一个文件夹。「远程扫描并自动下架」的任务会把这次扫描到"
    "的商品全部自动确认并直接执行下架，不需要人在这台主机上确认——"
    "如果不希望这样，分机那边就只提交「仅扫描」的任务。"
)


class RemoteJobsSettingsWidget(QWidget):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        explanation = QLabel(_EXPLANATION)
        explanation.setWordWrap(True)
        explanation.setObjectName("hintLabel")
        layout.addWidget(explanation)

        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("共享文件夹路径："))
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText(r"例如：\\192.168.1.10\temu-jobs 或 D:\temu-jobs")
        folder_row.addWidget(self.folder_edit, stretch=1)
        browse_button = QPushButton("浏览…")
        browse_button.clicked.connect(self._on_browse)
        folder_row.addWidget(browse_button)
        layout.addLayout(folder_row)

        self.enabled_checkbox = QCheckBox("开启监听（保存后立即生效）")
        layout.addWidget(self.enabled_checkbox)

        button_row = QHBoxLayout()
        save_button = QPushButton("保存设置")
        save_button.setObjectName("primaryButton")
        save_button.clicked.connect(self._on_save)
        button_row.addWidget(save_button)
        button_row.addStretch(1)
        layout.addLayout(button_row)

        self.status_label = QLabel("尚未保存设置。")
        self.status_label.setObjectName("hintLabel")
        layout.addWidget(self.status_label)

        layout.addStretch(1)

        self._load_current()

    def _load_current(self) -> None:
        config = load_remote_config()
        self.folder_edit.setText(config.root_dir)
        self.enabled_checkbox.setChecked(config.enabled)
        self._refresh_status(config)

    def _refresh_status(self, config: RemoteConfig) -> None:
        if not config.root_dir:
            self.status_label.setText("还没有配置共享文件夹路径。")
        elif config.enabled:
            self.status_label.setText(f"监听已开启，共享文件夹：{config.root_dir}")
        else:
            self.status_label.setText(f"监听已关闭，共享文件夹：{config.root_dir}")

    def _on_browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "选择共享文件夹")
        if path:
            self.folder_edit.setText(path)

    def _on_save(self) -> None:
        root_dir = self.folder_edit.text().strip()
        enabled = self.enabled_checkbox.isChecked()
        if enabled and not root_dir:
            QMessageBox.warning(self, "保存设置", "开启监听前，请先填写共享文件夹路径。")
            return

        config = RemoteConfig(root_dir=root_dir, enabled=enabled)
        save_remote_config(config)
        self._refresh_status(config)
        QMessageBox.information(self, "保存成功", "接口程序设置已保存。")
