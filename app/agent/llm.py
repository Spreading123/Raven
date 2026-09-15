"""LLM 客户端：基于 OpenAI 兼容接口的轻量封装。"""
from __future__ import annotations

from typing import Any
import os

from config.settings import config
from config.provider_store import get_api_key
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_persisted_api_key() -> str:
    """回退查找“历史已保存”的当前供应商 API Key（providers.json 优先，其次 .env）。

    背景：启动时 UI 为避免重复重建客户端，不会立即把已保存的 key 应用到
    ``config.llm``，导致点击历史会话等不经过“应用配置”的路径里 ``config.llm.api_key``
    仍为空——即使该供应商早已在 providers.json 保存过 key，也会被误判为“未配置”。

    此函数先检查**当前供应商**（按 base_url/model 推断）已保存的 key 并回退使用，
    避免误报；同时不会用错供应商的 key 发到错误端点而 401。若当前供应商确实未保存，
    则返回空串，交由上层给出“未配置”提示。
    """
    current = config.llm.match_provider()
    if current is None:
        return ""
    env_key = os.getenv(current.api_key_env, "") if current.api_key_env else ""
    return get_api_key(current.name, env_key)

# 系统提示词，可调整
DEFAULT_SYSTEM_PROMPT = (
    "你是一个专业的桌面助手 Agent。请用简洁、清晰的中文回答用户的问题，"
    "并尽力帮助用户完成任务。"
)


class LLMClient:
    """封装 LLM 对话请求（支持工具调用）。"""

    def __init__(self) -> None:
        # openai 库导入较重（约 1.5s），延迟到真正使用时才加载，
        # 避免拖慢应用启动。这里仅在首次创建客户端时导入一次。
        from openai import OpenAI  # noqa: PLC0415

        api_key = config.llm.api_key or _resolve_persisted_api_key()
        if not api_key:
            # 未配置 API Key 时不要用假 key 发送（否则服务器会返回 401 且提示
            # “API key format is incorrect”），直接抛出清晰的配置错误供上层提示。
            raise ValueError(
                "尚未配置 API Key，请在右上角选择供应商并填写 API Key 后重试。"
            )
        self._client = OpenAI(
            api_key=api_key,
            base_url=config.llm.base_url,
            timeout=config.llm.timeout,
        )
        self._messages: list[dict[str, Any]] = [
            {"role": "system", "content": DEFAULT_SYSTEM_PROMPT}
        ]

    def reset(self) -> None:
        """清空对话历史（保留系统提示）。"""
        self._messages = self._messages[:1]

    def add_user_message(self, content: str | list) -> None:
        """追加一条用户消息。

        ``content`` 可为纯文本字符串（旧行为，兼容），也可为 OpenAI 标准的
        content 块数组（多模态），例如::

            [
                {"type": "text", "text": "描述这张图片"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,..."}},
            ]

        底层仅负责透传；多模态是否生效取决于所选模型是否支持视觉输入。
        """
        self._messages.append({"role": "user", "content": content})

    def add_assistant_message(self, content: str) -> None:
        self._messages.append({"role": "assistant", "content": content})

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        """将工具执行结果回传给模型。"""
        self._messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        })

    def chat(
        self,
        tools: list[dict[str, Any]] | None = None,
        *,
        stream: bool = False,
        **kwargs: Any,
    ) -> Any:
        """发送对话请求。

        Args:
            tools: 可选工具定义列表（OpenAI tool calling 格式）。
            stream: 是否开启流式。为 True 时返回一个可迭代对象，
                逐块产出 ChatCompletionChunk（供上层边收边展示）。
            **kwargs: 透传给 API 的其它参数（如 temperature）。

        Returns:
            stream=False 时返回完整 ChatCompletion 响应；
            stream=True 时返回逐块迭代器。
        """
        try:
            params: dict[str, Any] = {
                "messages": self._messages,
                "model": config.llm.model,
                "stream": stream,
                "temperature": config.llm.temperature,
                "max_tokens": config.llm.max_tokens,
            }
            if tools:
                params["tools"] = tools
            params.update(kwargs)
            return self._client.chat.completions.create(**params)
        except Exception as exc:  # noqa: BLE001
            logger.exception("LLM 请求失败")
            # 若请求中包含图片内容块，多半是当前模型不支持多模态；补充可操作提示，
            # 帮助用户定位（UI 层已做白名单拦截，此处为最后一道防线）。
            hint = ""
            if any(
                isinstance(m.get("content"), list)
                for m in self._messages
                if isinstance(m.get("content"), list)
            ):
                hint = "；若当前模型不支持多模态（看图），请移除图片或切换到支持视觉的模型"
            raise RuntimeError(f"LLM 请求失败: {exc}{hint}") from exc
