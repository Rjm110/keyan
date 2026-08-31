"""科研协作中的角色 Agent。

每个角色都是一个标准 CubePi Agent：配好角色提示词 + 一组*工具槽位*声明。
槽位只是声明了未来会提供的能力名，目前尚未注册具体实现。后续注册真正的
AgentTools 是单独一步——提示词里已经描述了这些工具的作用，因此注册后
Agent 的行为可以保持一致。
"""

from __future__ import annotations

from collections.abc import Sequence

from cubepi import Agent
from cubepi.agent.types import AgentTool
from cubepi.middleware.base import Middleware
from cubepi.providers.base import BoundModel

from coop.types import Role

CODER_TOOL_SLOTS: tuple[str, ...] = (
    "run_experiment",
    "write_program",
    "list_baseline_files",
    "read_file",
)

RESEARCHER_TOOL_SLOTS: tuple[str, ...] = (
    "search_papers",
    "read_paper",
    "save_paper_notes",
)

TOOL_SLOTS: dict[Role, tuple[str, ...]] = {
    Role.CODER: CODER_TOOL_SLOTS,
    Role.RESEARCHER: RESEARCHER_TOOL_SLOTS,
}

# 角色系统提示词面向模型，保持英文以与库内其他示例一致；注释为中文。
_ROLE_SYSTEM_PROMPTS: dict[Role, str] = {
    Role.CODER: """\
You are the coding agent in a research collaboration.

Your job: validate the uploaded baseline by writing and running small
programs or experiments, and report what you find (reproducibility,
correctness, performance).

Planned tools (not registered yet): {slots}.
Until they are available, describe in plain text what you would run and
what you expect to learn.

Always answer the assigned task directly. Use the shared project context
appended to your system prompt for state you need.
""",
    Role.RESEARCHER: """\
You are the researcher agent in a research collaboration.

Your job: find and organize papers relevant to the project, summarize
their methods, and note how they compare to the baseline.

Planned tools (not registered yet): {slots}.
Until they are available, describe in plain text which papers you would
collect and why.

Always answer the assigned task directly. Use the shared project context
appended to your system prompt for state you need.
""",
}


def role_prompt(role: Role) -> str:
    """渲染某个角色的系统提示词，并列出其工具槽位。"""
    slots = ", ".join(TOOL_SLOTS[role])
    return _ROLE_SYSTEM_PROMPTS[role].format(slots=slots)


def make_role_agent(
    role: Role,
    *,
    model: BoundModel,
    tools: Sequence[AgentTool] = (),
    middleware: Sequence[Middleware] | None = None,
) -> Agent:
    """按给定科研角色构建一个 CubePi Agent。"""
    return Agent(
        model=model,
        system_prompt=role_prompt(role),
        tools=list(tools),
        middleware=list(middleware) if middleware else None,
    )


def make_coder_agent(
    *,
    model: BoundModel,
    tools: Sequence[AgentTool] = (),
    middleware: Sequence[Middleware] | None = None,
) -> Agent:
    """构建编码 Agent（负责验证上传的 baseline）。"""
    return make_role_agent(Role.CODER, model=model, tools=tools, middleware=middleware)


def make_researcher_agent(
    *,
    model: BoundModel,
    tools: Sequence[AgentTool] = (),
    middleware: Sequence[Middleware] | None = None,
) -> Agent:
    """构建研究员 Agent（负责搜索与整理论文）。"""
    return make_role_agent(
        Role.RESEARCHER, model=model, tools=tools, middleware=middleware
    )
