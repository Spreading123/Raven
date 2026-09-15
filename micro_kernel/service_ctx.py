"""服务上下文：轻量服务容器。

插件之间不直接互相 import，而是通过 ServiceContext 获取共享服务，
实现依赖解耦。这里用最简单的注册/获取，避免引入重型 DI 框架。
"""
from __future__ import annotations

from typing import Any


class ServiceContext:
    """按名称注册/获取共享服务的容器。"""

    def __init__(self) -> None:
        self._services: dict[str, Any] = {}

    def set(self, name: str, service: Any) -> None:
        """注册服务（同名覆盖）。"""
        self._services[name] = service

    def get(self, name: str) -> Any:
        """获取服务，不存在则抛出 KeyError。"""
        return self._services[name]

    def has(self, name: str) -> bool:
        """是否已注册某服务。"""
        return name in self._services
