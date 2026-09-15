"""应用路径工具：兼容源码运行与打包运行（PyInstaller / Nuitka）。

两种运行形态：
  1. 源码运行：``python main.py`` —— 项目根即 ``app/utils/`` 上三级。
  2. 打包运行（PyInstaller OneDir / Nuitka --standalone）：
     - PyInstaller 只读资源根为 ``sys._MEIPASS``，exe 在 ``dist/<name>/``；
     - Nuitka 将 ``--include-data-dir`` 的资源放到 exe 同级（dist 根）。

统一约定：
  - ``APP_ROOT``      —— 可写数据根（.env、logs、workspace 沙箱）。
                         打包后为 exe 同级目录，源码运行为项目根。
  - ``RESOURCE_ROOT`` —— 只读资源根（ui/*.ui、ui/styles/*.qss）。
                         打包后为 exe 同级（或 _MEIPASS），源码运行为项目根。
"""
from __future__ import annotations

import builtins
import sys
from pathlib import Path

# 源码项目根：app/utils/paths.py -> 项目根
_SRC_ROOT = Path(__file__).resolve().parent.parent.parent

# PyInstaller OneDir 的只读资源根（打包后存在）
_MEIPASS: str | None = getattr(sys, "_MEIPASS", None)


def _is_pyinstaller() -> bool:
    return bool(getattr(sys, "frozen", False)) and _MEIPASS is not None


def _is_nuitka() -> bool:
    # Nuitka 编译后在 builtins 中注入 __compiled__
    return "__compiled__" in dir(builtins)


def _is_compiled() -> bool:
    return _is_pyinstaller() or _is_nuitka() or bool(getattr(sys, "frozen", False))


def _exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _app_root() -> Path:
    """可写数据根：打包后为 exe 同级目录；源码运行为项目根。"""
    if _is_compiled():
        return _exe_dir()
    return _SRC_ROOT


def _resource_root() -> Path:
    """只读资源根：优先 exe 同级，其次 _MEIPASS，最后源码根。"""
    if _is_compiled():
        # PyInstaller：_MEIPASS（只读资源所在）
        if _MEIPASS:
            return Path(_MEIPASS)
        # Nuitka：资源（ui/ 等）放在 exe 同级（dist 根）
        return _exe_dir()
    return _SRC_ROOT


# 模块级常量，供各处直接 import
APP_ROOT = _app_root()
RESOURCE_ROOT = _resource_root()
