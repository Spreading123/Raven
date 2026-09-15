"""日志工具：统一格式与输出（控制台 + 文件）。"""
from __future__ import annotations

import logging
import sys

from app.utils.paths import APP_ROOT

LOG_DIR = APP_ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)

_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str = "desktop_agent") -> logging.Logger:
    """获取应用日志器（控制台 + 文件输出）。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(_FORMAT, _DATE))
    logger.addHandler(console)

    file = logging.FileHandler(LOG_DIR / "app.log", encoding="utf-8")
    file.setFormatter(logging.Formatter(_FORMAT, _DATE))
    logger.addHandler(file)

    return logger
