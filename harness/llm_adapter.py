"""LLM 适配插件：统一模型调用入口，支持 thinking 剥离。

复用 app/agent/llm.py 的 LLMClient（OpenAI 兼容），对外提供简洁的
chat() 接口，并把响应中的思考内容（reasoning）与正文分开返回，
使上层（agent_loop）无需关心具体 provider 差异。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from micro_kernel.plugin import Plugin
from app.agent.llm import LLMClient

# 服务名常量，供其它插件通过 ServiceContext 获取本插件
SERVICE_NAME = "llm"


@dataclass
class LLMResponse:
    """一次模型调用的结果，thinking 与正文分离。"""

    content: str
    thinking: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


class LLMAdapter(Plugin):
    """封装 LLMClient，剥离 thinking 并规范返回结构。"""

    def setup(self) -> None:
        # 客户端惰性初始化：openai 库导入较重（约 1.5s），
        # 推迟到首次 chat() 时才加载，避免拖慢应用启动。
        self._client = None
        self.ctx.set(SERVICE_NAME, self)

    def _ensure_client(self) -> "LLMClient":
        if self._client is None:
            self._client = LLMClient()
        return self._client

    def set_provider(self, base_url: str, model: str, api_key: str) -> None:
        """运行时切换供应商：更新配置并丢弃已缓存的客户端。

        仅当 base_url / model / api_key 任一发生变化时才重建客户端；
        否则复用现有客户端，避免每次发送都重建（openai 库构造较慢）。
        """
        from config.settings import config

        changed = (
            config.llm.base_url != base_url
            or config.llm.model != model
            or config.llm.api_key != api_key
        )
        config.llm.apply_provider(base_url, model, api_key)
        if changed:
            self._client = None


    def reset(self) -> None:
        # 惰性初始化前调用 reset 直接返回（无历史可清）
        if self._client is not None:
            self._client.reset()

    def load_history(self, history: list[tuple[str, str]]) -> None:
        """把一段会话历史重放到 LLM 上下文（先清空，再按序加入 user/assistant）。

        用于切换/查看历史会话时，让底层 LLM 上下文与当前显示的会话保持一致，
        避免切换后带着上一个会话的上下文发消息。

        客户端是惰性创建的：**仅当客户端已初始化时才同步**——未初始化说明还没
        发过任何消息、本就没有可同步的上下文，直接跳过，避免仅为“查看/切换
        历史”而触发昂贵的 openai 客户端构建（import 较重，约 1.5s）。
        """
        self.reset()
        if self._client is None:
            return
        for role, text in history:
            if role == "user":
                self._client.add_user_message(text)
            elif role == "assistant":
                self._client.add_assistant_message(text)
            # tool / error 不进入 LLM 上下文（会话记录中不含工具调用细节）

    def add_user_message(self, content: str | list) -> None:
        """追加用户消息。

        ``content`` 可为纯文本字符串，也可为 OpenAI 内容块数组（多模态：
        文本块 + image_url 块），由上层决定。纯文本接口的调用方无需改动。
        """
        self._ensure_client().add_user_message(content)

    def add_assistant_message(self, content: str) -> None:
        self._ensure_client().add_assistant_message(content)

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._ensure_client().add_tool_result(tool_call_id, content)

    def chat(self, tools: list[dict[str, Any]] | None = None) -> LLMResponse:
        """调用模型并返回规范化的 LLMResponse。

        思考内容从响应中剥离，不进入对话历史（DSH 规范）。
        """
        raw = self._ensure_client().chat(tools=tools)
        message = raw.choices[0].message

        thinking = getattr(message, "reasoning_content", None) or ""
        content = message.content or ""

        tool_calls = []
        for call in message.tool_calls or []:
            tool_calls.append({
                "id": call.id,
                "name": call.function.name,
                "arguments": call.function.arguments,
            })

        return LLMResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
        )

    def chat_stream(
        self,
        tools: list[dict[str, Any]] | None = None,
        on_chunk: callable | None = None,
    ) -> LLMResponse:
        """流式调用模型，逐块回调正文增量。

        Args:
            tools: 可选工具定义列表（OpenAI tool calling 格式）。
            on_chunk: 每收到一段正文增量即以 ``on_chunk(str)`` 回调，
                供上层实时展示。思考内容与工具调用增量不回调，仅累积。

        Returns:
            与 chat() 相同的完整 LLMResponse（流式累积结果）。
        """
        raw = self._ensure_client().chat(tools=tools, stream=True)

        content_parts: list[str] = []
        thinking_parts: list[str] = []
        # index -> {"id","name","arguments"}，工具调用参数按流式增量拼接
        tool_acc: dict[int, dict[str, Any]] = {}

        for chunk in raw:
            if not chunk.choices or chunk.choices[0].delta is None:
                continue
            delta = chunk.choices[0].delta

            if delta.content:
                content_parts.append(delta.content)
                if on_chunk:
                    on_chunk(delta.content)

            reasoning = getattr(delta, "reasoning_content", None)
            if reasoning:
                thinking_parts.append(reasoning)

            for tc in delta.tool_calls or []:
                slot = tool_acc.setdefault(
                    tc.index,
                    {"id": tc.id or "", "name": "", "arguments": ""},
                )
                if tc.function:
                    if tc.function.name:
                        slot["name"] += tc.function.name
                    if tc.function.arguments:
                        slot["arguments"] += tc.function.arguments

        tool_calls = [
            {"id": v["id"], "name": v["name"], "arguments": v["arguments"]}
            for v in tool_acc.values()
        ]

        return LLMResponse(
            content="".join(content_parts),
            thinking="".join(thinking_parts),
            tool_calls=tool_calls,
        )

