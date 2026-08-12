"""后台线程：跑 scan/apply 这类耗时的 Playwright 操作，不卡住界面。

每个 worker 自己开一个 SQLite 连接（在线程内部开、内部用、内部关），不跨线程
共享 Store/Connection 对象——sqlite3 的默认连接不是线程安全的。

注意：这两个类都不能起名叫 self.start/self.run/self.quit/self.wait 之类的
实例属性——QThread 自带同名方法，起了会把继承来的方法覆盖掉（之前就因为
`self.start = start_date` 踩过这个坑，导致 `worker.start()` 变成"调用一个
字符串"而崩溃，线程根本没跑起来）。
"""
from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QThread, Signal

from temu_delisting import actions
from temu_delisting.config import Settings
from temu_delisting.logging_setup import get_logger, setup_logging
from temu_delisting.store import open_store

from .errors import friendly_message


class ScanWorker(QThread):
    log_line = Signal(str)
    finished_ok = Signal(object)  # actions.ScanResult
    failed = Signal(str)  # 人话错误提示（完整堆栈已经写进日志文件）

    def __init__(self, settings: Settings, start_date: str, end_date: str) -> None:
        super().__init__()
        self.settings = settings
        self.start_date = start_date
        self.end_date = end_date

    def run(self) -> None:
        # setup_logging 必须在这个工作线程里调用（不是主线程），日志才会按
        # "这个线程自己"分开记，多个账号并发跑的时候不会互相把日志文件挤掉。
        setup_logging(self.settings.log_dir)
        try:
            with open_store(self.settings.db_path) as store:
                result = actions.run_scan(
                    self.settings, store, self.start_date, self.end_date, log=self.log_line.emit
                )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001 — 转成信号交给 GUI 侧显示人话提示
            get_logger().exception("scan 失败")
            self.failed.emit(friendly_message(exc))


class ApplyWorker(QThread):
    log_line = Signal(str)
    progress_changed = Signal(int, int, str)  # 当前第几个, 总数, 当前 SPU ID
    finished_ok = Signal(object)  # actions.ApplyResult
    failed = Signal(str)

    def __init__(
        self,
        settings: Settings,
        batch_id: str,
        dry_run: bool,
        should_stop: Callable[[], bool],
    ) -> None:
        super().__init__()
        self.settings = settings
        self.batch_id = batch_id
        self.dry_run = dry_run
        self.should_stop = should_stop

    def run(self) -> None:
        setup_logging(self.settings.log_dir)
        try:
            with open_store(self.settings.db_path) as store:
                result = actions.run_apply(
                    self.settings,
                    store,
                    self.batch_id,
                    dry_run=self.dry_run,
                    log=self.log_line.emit,
                    progress=lambda current, total, spu_id: self.progress_changed.emit(
                        current, total, spu_id
                    ),
                    should_stop=self.should_stop,
                )
            self.finished_ok.emit(result)
        except Exception as exc:  # noqa: BLE001
            get_logger().exception("apply 失败")
            self.failed.emit(friendly_message(exc))
