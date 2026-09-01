"""Agent 装配工厂：构建科研助手 Agent。

- 工具：文件系统工具（fs_tools）+ 论文工具（paper_tools）+ ask_user（模型主动提问）
- HITL：ConfirmToolCallMiddleware 拦截修改类工具（write_file/replace_in_file），
  修改前弹窗确认（approve/deny/edit）
- 持久化：SQLiteCheckpointer + thread_id
- 沙箱：fs_tools 的 workspace_root = 当前项目目录（project_dir），
  agent 只能读写当前项目代码，不能跨项目
"""

from __future__ import annotations

from pathlib import Path

from cubepi import Agent
from cubepi.agent.types import AgentContext
from cubepi.checkpointer.base import Checkpointer
from cubepi.hitl import ConfirmToolCallMiddleware, ask_user_tool
from cubepi.hitl.channel import CheckpointedChannel
from cubepi.providers.base import AssistantMessage, BoundModel, Message

from app.config import AppConfig
from app.system_prompt import build_system_prompt
from app.tools.fs_tools import make_fs_tools
from app.tools.paper_tools import make_paper_tools

# 需要用户确认的修改类工具
REQUIRE_CONFIRM = {"write_file", "replace_in_file"}


def _convert_to_llm(messages: list[Message], *, ctx: AgentContext) -> list[Message]:
    """过滤掉空的错误 assistant 消息（stop_reason=error 且无内容）。

    之前 API key 无效时，agent 会把 stop_reason="error" 的空 assistant 消息
    持久化到 checkpointer；恢复历史后这些消息（无 content、无 tool_calls）
    发给 OpenAI 兼容 API 会报 "content or tool_calls must be set"。
    这里在发给模型前过滤掉它们。
    """
    del ctx
    return [
        m
        for m in messages
        if not (
            isinstance(m, AssistantMessage)
            and m.stop_reason == "error"
            and not m.content
        )
    ]


def build_agent(
    *,
    model: BoundModel,
    config: AppConfig,
    checkpointer: Checkpointer,
    thread_id: str,
    project_dir: Path,
    run_id: str | None = None,
) -> Agent:
    """构建科研助手 Agent（每个请求新建，共享 checkpointer）。

    project_dir：当前项目代码目录（agent 沙箱根，只能读写该目录）。
    run_id：HITL 绑定标识。prompt(run_id=...) 必须传相同值；
    respond() 会从 checkpointer 恢复 run_id 并校验绑定。
    """
    fs_tools = make_fs_tools(project_dir, config.backups_dir)
    paper_tools = make_paper_tools(config.papers_dir)
    channel = CheckpointedChannel(
        checkpointer=checkpointer, thread_id=thread_id, run_id=run_id
    )

    agent: Agent = Agent(
        model=model,
        system_prompt=build_system_prompt(config, project_dir),
        tools=[*fs_tools, *paper_tools, ask_user_tool(channel)],
        convert_to_llm=_convert_to_llm,
        middleware=[
            ConfirmToolCallMiddleware(
                channel,
                require_confirm=REQUIRE_CONFIRM,
                details_fn=lambda ctx: {
                    "tool": ctx.tool_call.name,
                    "args": ctx.args.model_dump()
                    if hasattr(ctx.args, "model_dump")
                    else str(ctx.args),
                },
            ),
        ],
        checkpointer=checkpointer,
        thread_id=thread_id,
        channel=channel,
    )
    return agent
