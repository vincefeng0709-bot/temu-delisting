"""把每次运行的关键事件同时写到终端和一个带时间戳的日志文件里，方便事后审计
"跑没跑、跑了哪些、出过什么错"。

GUI 支持多账号切换，每个账号的日志各自存在自己的目录下——调用方（GUI 侧
在每次开始扫描/下架前）应该传当前选中账号的 log_dir，本函数如果发现目标
目录变了，会把日志切到新账号的目录下，而不是死认第一次启动时的账号
（早期版本只在第一次调用时初始化一次，account 切换后日志其实还在写旧
账号的目录，事后排查时经常找错日志文件）。同一个账号内重复调用不会
反复开新文件。
"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "temu_delisting"

_current_log_dir: Path | None = None


def setup_logging(log_dir: Path) -> logging.Logger:
    global _current_log_dir
    log_dir = Path(log_dir)

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if _current_log_dir == log_dir and logger.handlers:
        return logger

    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now():%Y%m%d_%H%M%S}.log"

    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(file_handler)
    _current_log_dir = log_dir

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
