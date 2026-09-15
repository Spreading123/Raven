"""工具注册表：定义 Agent 可调用的工具及其执行逻辑。"""
from __future__ import annotations

from typing import Any, Callable


class Tool:
    """一个可被 LLM 调用的工具。"""

    def __init__(self, name: str, description: str, func: Callable[..., str],
                 parameters: dict[str, Any]) -> None:
        self.name = name
        self.description = description
        self.func = func
        self.parameters = parameters

    def to_schema(self) -> dict[str, Any]:
        """转换为 OpenAI 工具定义格式。"""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def run(self, arguments: dict[str, Any]) -> str:
        """执行工具并返回结果字符串。"""
        return self.func(**arguments)


class ToolRegistry:
    """管理所有可用工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def schemas(self) -> list[dict[str, Any]]:
        return [t.to_schema() for t in self._tools.values()]

    def names(self) -> list[str]:
        """返回所有工具名。"""
        return list(self._tools)

    def run(self, name: str, arguments: dict[str, Any]) -> str:
        tool = self.get(name)
        if tool is None:
            return f"未知工具: {name}"
        return tool.run(arguments)
