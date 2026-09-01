from cubepi.agent.types import AgentContext
from cubepi.providers.base import (
    AssistantMessage,
    TextContent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)

from app.agent_factory import _convert_to_llm


def _context() -> AgentContext:
    return AgentContext(system_prompt="", messages=[])


def test_convert_to_llm_drops_incomplete_tool_cycle() -> None:
    assistant = AssistantMessage(
        content=[ToolCall(id="call-1", name="read_file", arguments={})],
        stop_reason="tool_use",
    )
    messages = [
        UserMessage(content=[TextContent(text="继续")]),
        assistant,
    ]

    assert _convert_to_llm(messages, ctx=_context()) == messages[:1]


def test_convert_to_llm_keeps_complete_tool_cycle() -> None:
    assistant = AssistantMessage(
        content=[ToolCall(id="call-1", name="read_file", arguments={})],
        stop_reason="tool_use",
    )
    result = ToolResultMessage(
        tool_call_id="call-1",
        tool_name="read_file",
        content=[TextContent(text="内容")],
    )
    messages = [
        UserMessage(content=[TextContent(text="读取")]),
        assistant,
        result,
    ]

    assert _convert_to_llm(messages, ctx=_context()) == messages