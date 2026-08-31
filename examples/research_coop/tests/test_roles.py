"""角色 Agent 工厂的测试（尚未注册任何工具）。"""

from __future__ import annotations

from cubepi.middleware.base import Middleware
from cubepi.providers.faux import faux_assistant_message

from coop.roles import (
    TOOL_SLOTS,
    make_coder_agent,
    make_researcher_agent,
    role_prompt,
)
from coop.types import Role


class TestRolePrompts:
    def test_coder_prompt_mentions_tool_slots(self):
        prompt = role_prompt(Role.CODER)
        assert "coding agent" in prompt
        assert "run_experiment" in prompt

    def test_researcher_prompt_mentions_tool_slots(self):
        prompt = role_prompt(Role.RESEARCHER)
        assert "researcher" in prompt
        assert "search_papers" in prompt

    def test_tool_slots_cover_both_roles(self):
        assert set(TOOL_SLOTS) == {Role.CODER, Role.RESEARCHER}


class TestRoleAgents:
    def test_factory_returns_agents_with_role_prompts(self, faux_model):
        coder = make_coder_agent(model=faux_model)
        researcher = make_researcher_agent(model=faux_model)

        assert "coding agent" in coder._state.system_prompt
        assert "researcher" in researcher._state.system_prompt

    def test_tool_slots_declared_but_no_tools_registered(self, faux_model):
        agent = make_coder_agent(model=faux_model)
        assert not agent._state.tools
        assert TOOL_SLOTS[Role.CODER]

    async def test_agent_runs_a_turn_with_faux_provider(
        self, faux_model, faux_provider
    ):
        faux_provider.set_responses([faux_assistant_message("paper survey summary")])
        agent = make_researcher_agent(model=faux_model)

        await agent.prompt("Find papers on the baseline.")

        messages = agent.state.messages
        assert messages[-1].error_message is None
        assert messages[-1].content[0].text == "paper survey summary"

    async def test_middleware_marker_reaches_system_prompt(
        self, faux_model, faux_provider
    ):
        class MarkerTail(Middleware):
            async def transform_system_prompt(self, system_prompt, *, ctx, signal=None):
                return system_prompt + "\nMARKER"

        agent = make_coder_agent(model=faux_model, middleware=[MarkerTail()])

        await agent.prompt("hi")

        assert "MARKER" in faux_provider.prompt_cache["default"]


class TestRolePromptText:
    """角色提示词默认文案为英文、面向模型；此处仅确认提示词可渲染且包含槽位。"""

    def test_prompts_are_renderable(self):
        for role in Role:
            assert "{slots}" not in role_prompt(role)
