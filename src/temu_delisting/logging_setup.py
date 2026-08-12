"""把每次运行的关键事件同时写到终端和一个带时间戳的日志文件里，方便事后审计
"跑没跑、跑了哪些、出过什么错"。

GUI 支持多账号并发运行——一个账号在跑扫描的同时可以另开一个账号跑下架，
各自在自己的后台线程（QThread）里。如果日志还是像以前那样挂在一个全局单例
logger 上，两个账号的 setup_logging() 前后脚调用会互相把对方的日志文件"挤
下线"，事后完全分不清哪条日志是哪个账号产生的。这里改成按**线程**分：
setup_logging() 必须在真正要跑扫描/下架的那个线程里调用（worker.py 在
run() 一开始就调），之后同一线程内调用 get_logger() 会自动拿到这个线程
专属的 logger + 文件句柄，不会跟其他线程互相干扰。主线程（比如 GUI 启动
时打印的那次身份横幅）不受影响，走的是主线程自己的 logger。
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "temu_delisting"

_thread_local = threading.local()


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir = Path(log_dir)
    logger_name = f"{LOGGER_NAME}.t{threading.get_ident()}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if getattr(_thread_local, "log_dir", None) == log_dir and logger.handlers:
        _thread_local.logger_name = logger_name
        return logger

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now():%Y%m%d_%H%M%S}.log"
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)

    _thread_local.log_dir = log_dir
    _thread_local.logger_name = logger_name

    return logger


def get_logger() -> logging.Logger:
    logger_name = getattr(_thread_local, "logger_name", LOGGER_NAME)
    return logging.getLogger(logger_name)
