"""内置工具定义：当前不注册任何工具。

read_file / write_file 等文件读写能力已彻底移除（不向 LLM 暴露工具定义），
避免模型误调用文件操作。后续如需启用文件能力，在此追加 Tool 定义即可
（文件操作限制在 workspace 目录内，见 WORKSPACE 注释）。
"""
from __future__ import annotations

from app.agent.tools import Tool

# workspace 根目录：exe 同级（打包后）或项目根（源码），作为文件操作的唯一合法范围
# WORKSPACE = APP_ROOT
# （当前未启用文件操作，故不引入 APP_ROOT，待实现时再放开）


def builtins() -> list[Tool]:
    """返回内置工具定义列表。

    当前返回空列表：文件读写工具已移除，不再向 LLM 暴露，
    以免模型尝试调用未实现的 read_file / write_file。
    """
    return []
