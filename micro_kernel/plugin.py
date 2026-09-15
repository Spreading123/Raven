"""插件基类与插件管理器。

插件通过生命周期钩子（setup/teardown）接入系统，
并用 ServiceContext 获取服务、EventBus 通信，不直接依赖其它插件。
"""
from __future__ import annotations

from typing import Any, Type

from micro_kernel.event_bus import EventBus
from micro_kernel.service_ctx import ServiceContext


class Plugin:
    """所有插件的基础类。

    子类实现 setup/teardown 完成初始化与清理。
    """

    def __init__(self, ctx: ServiceContext, bus: EventBus) -> None:
        self.ctx = ctx
        self.bus = bus

    def setup(self) -> None:
        """初始化钩子，注册服务/订阅事件。"""

    def teardown(self) -> None:
        """清理钩子。"""


class PluginManager:
    """负责装配、启动、停止一组插件。"""

    def __init__(self, ctx: ServiceContext, bus: EventBus) -> None:
        self._ctx = ctx
        self._bus = bus
        self._plugins: list[Plugin] = []

    def install(self, plugin_type: Type[Plugin], *args: Any) -> Plugin:
        """实例化并启动一个插件，返回其实例。"""
        plugin = plugin_type(self._ctx, self._bus, *args)
        plugin.setup()
        self._plugins.append(plugin)
        return plugin

    def shutdown(self) -> None:
        """按启动逆序清理所有插件。"""
        for plugin in reversed(self._plugins):
            plugin.teardown()
        self._plugins.clear()
