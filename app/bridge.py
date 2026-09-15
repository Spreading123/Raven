"""DSH 桥接层：把 micro_kernel + harness 插件引擎桥接到 Qt GUI。

让 GUI 复用 DSH 核心引擎（Model + Harness = Agent），对外暴露与
app/agent/Agent 一致的 Qt 信号与接口，使 main_window 无需感知底层
是插件化引擎。线程管理仍由 MainWindow 的 _AgentWorker 负责，本类
不额外开线程，保持简洁（避免“线程套线程”）。

对应架构规划的 ``app/bridge.py``（阶段三，最小实现）。
"""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from micro_kernel import EventBus, PluginManager, ServiceContext
from harness.llm_adapter import LLMAdapter, SERVICE_NAME as LLM_SERVICE
from harness.tool_registry import ToolRegistryPlugin
from harness.agent_loop import (
    ReActLoop,
    EVENT_MESSAGE,
    EVENT_CHUNK,
    EVENT_TOOL_CALL,
)

from app.utils.logger import get_logger

logger = get_logger(__name__)


class DSHBridge(QObject):
    """把 DSH 插件引擎适配为 GUI 可用的 Agent 对象。

    信号语义与 app/agent/Agent 保持一致，便于 main_window 无缝替换：
        message_ready(str): 生成了一条助手消息。
        message_chunk(str): 助手消息的流式增量片段（正文逐块）。
        tool_called(str, str): 调用了某个工具（名称、参数）。
        finished(): 一次完整对话处理结束。
        error(str): 处理出错。
    """

    message_ready = Signal(str)
    message_chunk = Signal(str)
    tool_called = Signal(str, str)
    finished = Signal()
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        # 装配 DSH 引擎（与 cli_main 相同的插件组合）
        ctx = ServiceContext()
        bus = EventBus()
        manager = PluginManager(ctx, bus)
        manager.install(LLMAdapter)
        tool_registry = manager.install(ToolRegistryPlugin)
        self._loop = manager.install(ReActLoop)
        self._manager = manager
        self._ctx = ctx
        self._tool_registry = tool_registry

        # 事件总线 → Qt 信号（在 worker 线程内 emit，MainWindow 连接为队列连接，安全）
        bus.on(EVENT_MESSAGE, self._on_message)
        bus.on(EVENT_CHUNK, self._on_chunk)
        bus.on(EVENT_TOOL_CALL, self._on_tool_call)

    # ---- 与 app/agent/Agent 一致的公开接口 ----

    def reset(self) -> None:
        """清空对话历史。"""
        self._loop.reset()

    def load_history(self, history: list[tuple[str, str]]) -> None:
        """把一段会话历史重放到 LLM 上下文（先清空，再按序加入 user/assistant 消息）。

        用于切换历史会话时，让底层 LLM 上下文与当前显示的会话保持一致，
        避免切换后带着上一个会话的上下文发消息。
        若底层客户端尚未初始化（未发过消息），则跳过——查看/切换历史本身
        不需要真实 LLM 客户端，避免为此触发昂贵的 openai 客户端构建。
        """
        llm = self._ctx.get(LLM_SERVICE)
        llm.load_history(history)

    def tool_names(self) -> list[str]:
        """返回当前注册的所有工具名。"""
        return self._tool_registry.names()

    def set_provider(self, base_url: str, model: str, api_key: str) -> None:
        """运行时切换 LLM 供应商（base_url / model / api_key）。

        底层会重建 LLM 客户端，使切换立即生效。
        """
        llm = self._ctx.get(LLM_SERVICE)
        llm.set_provider(base_url, model, api_key)


    def request_interrupt(self) -> None:
        """请求中断当前处理（当前 DSH 主循环无中断位，预留接口）。"""
        # ReActLoop 尚未内置中断位；MainWindow 通过 _AgentWorker.requestInterruption()
        # 中断线程。此方法保留以维持与 Agent 的接口一致性。
        return

    def process(self, user_text: str | list) -> None:
        """同步处理用户输入，结果通过信号回传（由调用方置于线程中运行）。

        ``user_text`` 可为纯文本字符串，也可为 OpenAI 内容块数组（多模态），
        直接透传给 ReActLoop，保持对纯文本调用方的完全兼容。
        """
        try:
            self._loop.run(user_text)
        except Exception as exc:  # noqa: BLE001
            self.error.emit(str(exc))
            logger.error("DSH Agent 出错: %s", exc)
        finally:
            self.finished.emit()

    # ---- 事件回调（运行在 worker 线程）----

    def _on_message(self, text: str) -> None:
        self.message_ready.emit(text)

    def _on_chunk(self, chunk: str) -> None:
        self.message_chunk.emit(chunk)

    def _on_tool_call(self, name: str, arguments: str) -> None:
        self.tool_called.emit(name, arguments)

    def shutdown(self) -> None:
        """程序退出时清理插件资源。"""
        self._manager.shutdown()

