"""工具注册插件：管理 Agent 可调用的全部工具。

复用 app/agent/tools.py 的 ToolRegistry，并提供统一的服务访问，
使 agent_loop 通过 ServiceContext 获取工具，而不直接依赖具体实现。
"""
from __future__ import annotations

from typing import Any

from micro_kernel.plugin import Plugin
from app.agent.tools import Tool, ToolRegistry

SERVICE_NAME = "tool_registry"


class ToolRegistryPlugin(Plugin):
    """持有工具注册表并暴露为共享服务。"""

    def setup(self) -> None:
        self._registry = ToolRegistry()
        self._load_builtin_tools()
        self.ctx.set(SERVICE_NAME, self)

    def register(self, tool: Tool) -> None:
        self._registry.register(tool)

    def names(self) -> list[str]:
        return self._registry.names()

    def schemas(self) -> list[dict[str, Any]]:
        return self._registry.schemas()

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        return self._registry.run(name, arguments)

    def _load_builtin_tools(self) -> None:
        """注册 tools/ 目录下的内置工具。"""
        from tools import builtins  # 延迟导入，避免循环依赖

        for tool in builtins():
            self._registry.register(tool)
