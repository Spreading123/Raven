"""Raven 程序入口。"""
from __future__ import annotations

import sys

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

from app.main_window import MainWindow
from app.utils.logger import get_logger

logger = get_logger(__name__)


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Raven")
    # 强制使用 Windows 自带微软雅黑，保证界面字体一致
    app.setFont(QFont("Microsoft YaHei UI", 10))

    window = MainWindow()
    window.show()
    logger.info("应用启动")

    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

