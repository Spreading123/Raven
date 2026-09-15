"""阶段一 CLI 入口：验证 Model + Harness = Agent。

装配 micro_kernel + harness 插件，提供命令行对话交互，
观察 Agent 思考、工具调用与最终回答。
"""
from __future__ import annotations

from micro_kernel import EventBus, PluginManager, ServiceContext
from harness.llm_adapter import LLMAdapter
from harness.tool_registry import ToolRegistryPlugin
from harness.agent_loop import (
    ReActLoop,
    EVENT_MESSAGE,
    EVENT_THINKING,
    EVENT_TOOL_CALL,
)


def _build_agent():
    """装配内核与插件，返回可用的 agent_loop。"""
    ctx = ServiceContext()
    bus = EventBus()
    manager = PluginManager(ctx, bus)

    manager.install(LLMAdapter)
    manager.install(ToolRegistryPlugin)
    loop = manager.install(ReActLoop)

    bus.on(EVENT_THINKING, lambda t: print(f"[思考] {t}"))
    bus.on(EVENT_TOOL_CALL, lambda name, args: print(f"[工具] {name}({args})"))
    bus.on(EVENT_MESSAGE, lambda m: print(f"[回答] {m}"))

    return loop


def main() -> None:
    agent = _build_agent()
    print("已就绪。输入任务开始，输入 exit 退出。")
    while True:
        try:
            text = input(">>> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("exit", "quit"):
            break
        agent.run(text)


if __name__ == "__main__":
    main()
