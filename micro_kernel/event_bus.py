"""事件总线：发布/订阅，解耦生产与消费。

仅提供最小能力：订阅、发布、取消订阅。
用事件名 + 参数元组传递，不引入复杂的事件对象。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Callable

Handler = Callable[..., None]


class EventBus:
    """按事件名分组的发布/订阅总线。"""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)

    def on(self, event: str, handler: Handler) -> None:
        """订阅事件。"""
        self._handlers[event].append(handler)

    def off(self, event: str, handler: Handler) -> None:
        """取消订阅（不存在则忽略）。"""
        handlers = self._handlers.get(event)
        if handlers and handler in handlers:
            handlers.remove(handler)

    def emit(self, event: str, *args: Any) -> None:
        """发布事件，同步调用所有订阅者。"""
        for handler in list(self._handlers.get(event, ())):
            handler(*args)
