"""把每次运行的关键事件同时写到终端和一个带时间戳的日志文件里，方便事后审计
"跑没跑、跑了哪些、出过什么错"。"""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

LOGGER_NAME = "temu_delisting"


def setup_logging(log_dir: Path) -> logging.Logger:
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"{datetime.now():%Y%m%d_%H%M%S}.log"

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        file_handler = logging.FileHandler(log_path, encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)
