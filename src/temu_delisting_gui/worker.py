"""后台线程：跑 scan/apply 这类耗时的 Playwright 操作，不卡住界面。

每个 worker 自己开一个 SQLite 连接（在线程内部开、内部用、内部关），不跨线程
共享 Store/Connection 对象——sqlite3 的默认连接不是线程安全的。
"""
from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from temu_delisting import actions
from temu_delisting.config import Settings
from temu_delisting.logging_setup import get_logger
from temu_delisting.store import open_store


class ScanWorker(QThread):
    log_line = Signal(str)
    finished_ok = Signal(object)  # actions.ScanResult
    failed = Signal(str)  # 人话错误提示（完整堆栈已经写进日志文件）

    def __init__(self, settings: Settings, start_date: str, end_date: str) -> None:
        super().__init__()
        # 注意：不能叫 self.start/self.end —— QThread 自带一个 start() 方法用来
        # 启动这个线程，起同名的实例属性会把继承来的方法覆盖掉，导致
        # `worker.start()` 变成"调用一个字符串"而崩溃，线程根本不会跑起来。
        self.settings = settings
        self.start_date = start_date
        self.end_date = end_date

    def run(self) -> None:
        try:
            with open_store(self.settings.db_path) as store:
                result = actions.run_scan(
                    self.settings, store, self.start_date, self.end_date, log=self.log_line.emit
                )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 — 转成信号交给 GUI 侧显示人话提示
            get_logger().exception("scan 失败")
            self.failed.emit(str(exc))
