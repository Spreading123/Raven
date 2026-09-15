"""ReAct 主循环插件：Agent 的核心执行循环。

通过 ServiceContext 获取 llm 与 tool_registry，驱动
"模型思考 → 必要时调工具 → 继续" 的循环，直到模型给出最终答案。
主循环本身是插件，可被替换（DSH 精髓）。
"""
from __future__ import annotations

import json

from micro_kernel.plugin import Plugin
from harness.llm_adapter import SERVICE_NAME as LLM_SERVICE
from harness.tool_registry import SERVICE_NAME as TOOL_SERVICE

SERVICE_NAME = "agent_loop"

# 事件名：供上层（CLI/UI）订阅以观察运行过程
EVENT_MESSAGE = "agent.message"      # 最终回答
EVENT_THINKING = "agent.thinking"    # 思考内容
EVENT_TOOL_CALL = "agent.tool_call"  # 工具调用 (name, arguments)
EVENT_CHUNK = "agent.chunk"          # 最终回答的流式增量片段


class ReActLoop(Plugin):
    """基于 ReAct（Reason + Act）的对话/工具循环。"""

    def setup(self) -> None:
        self._llm = self.ctx.get(LLM_SERVICE)
        self._tools = self.ctx.get(TOOL_SERVICE)
        self.ctx.set(SERVICE_NAME, self)

    def run(self, user_text: str | list, max_steps: int = 5) -> str:
        """处理用户输入，返回最终回答文本。

        ``user_text`` 可为纯文本字符串，也可为 OpenAI 内容块数组（多模态：
        文本块 + image_url 块），透传给底层 add_user_message。
        """
        self._llm.add_user_message(user_text)
        for _ in range(max_steps):
            # 中断检查：在每次 LLM 请求前检查是否被请求中断（停止按钮）
            if self._is_interrupted():
                return self._finish("（已停止）")

            response = self._llm.chat_stream(
                tools=self._tools.schemas(),
                on_chunk=self._on_chunk,
            )

            if response.thinking:
                self.bus.emit(EVENT_THINKING, response.thinking)

            if not response.tool_calls:
                return self._finish(response.content)

            for call in response.tool_calls:
                # 工具调用前也检查中断
                if self._is_interrupted():
                    return self._finish("（已停止）")
                result = self._execute_tool(call)
                self._llm.add_tool_result(call["id"], result)

        return "已达到最大工具调用次数，请重试或简化问题。"

    @staticmethod
    def _is_interrupted() -> bool:
        """检查当前线程是否被请求中断（停止按钮 / 关闭窗口）。

        在 QThread 中运行时，QThread.requestInterruption() 会设置中断标志，
        这里通过 currentThread() 检查。非线程环境（如 CLI）直接返回 False。
        """
        try:
            from PySide6.QtCore import QThread
            thread = QThread.currentThread()
            if thread is not None and hasattr(thread, "isInterruptionRequested"):
                return thread.isInterruptionRequested()
        except Exception:
            pass
        return False

    def reset(self) -> None:
        """清空对话历史。"""
        self._llm.reset()

    def _on_chunk(self, chunk: str) -> None:
        """流式回调：把最终回答的增量片段转发到事件总线。"""
        self.bus.emit(EVENT_CHUNK, chunk)

    def _execute_tool(self, call: dict) -> str:
        """解析参数并执行单个工具调用，返回结果文本。"""
        name = call["name"]
        arguments = self._parse_arguments(call["arguments"])
        self.bus.emit(EVENT_TOOL_CALL, name, call["arguments"])
        return self._tools.run(name, arguments)

    def _finish(self, content: str) -> str:
        """记录最终回答并返回。"""
        self._llm.add_assistant_message(content)
        self.bus.emit(EVENT_MESSAGE, content)
        return content

    @staticmethod
    def _parse_arguments(raw: str) -> dict:
        """容错解析工具参数 JSON，失败时返回空字典。"""
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {}
