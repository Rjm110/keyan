"""Agent 集成测试：FauxProvider 驱动全流程 + HITL 确认。

覆盖：
1. 修改类工具触发 HITL 确认（approve 后执行）
2. 拒绝（deny）后工具被阻止
3. 完整流程：读文件 → 修改 → 确认 → 完成
"""

from __future__ import annotations

import asyncio

from cubepi.checkpointer.sqlite import SQLiteCheckpointer
from cubepi.hitl import ApproveAnswer
from cubepi.providers.faux import (
    FauxProvider,
    faux_assistant_message,
    faux_text,
    faux_tool_call,
)

from app.agent_factory import build_agent
from app.config import AppConfig


async def _await_pending(channel, *, timeout: float = 2.0) -> None:
    async def _wait():
        while channel.pending is None:
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(_wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"channel.pending did not become set within {timeout}s"
        ) from exc


def _make_faux_model(responses):
    provider = FauxProvider(provider_id="faux")
    provider.set_responses(responses)
    return provider.model("faux-model")


async def test_approve_executes_tool(app_config: AppConfig):
    """模型发起 replace_in_file → HITL 确认 approve → 工具执行。"""
    # 准备项目目录文件
    project_dir = app_config.projects_dir / "default"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "model.py").write_text("x = 1\nprint(x)\n")

    model = _make_faux_model(
        [
            faux_assistant_message(
                [
                    faux_text("I will edit model.py."),
                    faux_tool_call(
                        "replace_in_file",
                        {
                            "path": "model.py",
                            "old_text": "x = 1",
                            "new_text": "x = 2",
                        },
                        id="tc-1",
                    ),
                ],
                stop_reason="tool_use",
            ),
            faux_assistant_message("Done."),
        ]
    )

    async with SQLiteCheckpointer(str(app_config.db_path)) as cp:
        agent = build_agent(
            model=model,
            config=app_config,
            checkpointer=cp,
            thread_id="user:test-approve",
            project_dir=project_dir,
            run_id="run-approve",
        )
        channel = agent.channel

        # 宿主协程：等待 pending → approve
        async def host():
            await _await_pending(channel)
            req = channel.pending
            assert req is not None
            assert req.payload.kind == "approve"
            await channel.answer(req.question_id, ApproveAnswer(decision="approve"))

        task = asyncio.create_task(host())
        await agent.prompt("把 x 改成 2", run_id="run-approve")
        await task

        # 工具已执行
        content = (project_dir / "model.py").read_text()
        assert "x = 2" in content
        # 备份存在
        assert len(list(app_config.backups_dir.rglob("model.py"))) == 1


async def test_deny_blocks_tool(app_config: AppConfig):
    """HITL 确认 deny → 工具被阻止，文件不变。"""
    project_dir = app_config.projects_dir / "default"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "model.py").write_text("x = 1\nprint(x)\n")

    model = _make_faux_model(
        [
            faux_assistant_message(
                [
                    faux_text("I will edit model.py."),
                    faux_tool_call(
                        "replace_in_file",
                        {
                            "path": "model.py",
                            "old_text": "x = 1",
                            "new_text": "x = 2",
                        },
                        id="tc-1",
                    ),
                ],
                stop_reason="tool_use",
            ),
            faux_assistant_message("Understood, I won't edit."),
        ]
    )

    async with SQLiteCheckpointer(str(app_config.db_path)) as cp:
        agent = build_agent(
            model=model,
            config=app_config,
            checkpointer=cp,
            thread_id="user:test-deny",
            project_dir=project_dir,
            run_id="run-deny",
        )
        channel = agent.channel

        async def host():
            await _await_pending(channel)
            req = channel.pending
            assert req is not None
            await channel.answer(
                req.question_id, ApproveAnswer(decision="deny", reason="不要改")
            )

        task = asyncio.create_task(host())
        await agent.prompt("把 x 改成 2", run_id="run-deny")
        await task

        # 文件未被修改
        content = (project_dir / "model.py").read_text()
        assert "x = 1" in content
        assert "x = 2" not in content


async def test_full_flow_read_then_edit(app_config: AppConfig):
    """完整流程：模型先读文件，再发起修改，确认后完成。"""
    project_dir = app_config.projects_dir / "default"
    project_dir.mkdir(parents=True, exist_ok=True)
    (project_dir / "model.py").write_text("def predict(x):\n    return x * 2\n")

    model = _make_faux_model(
        [
            faux_assistant_message(
                [
                    faux_text("Let me read the file first."),
                    faux_tool_call(
                        "read_file",
                        {"path": "model.py"},
                        id="tc-1",
                    ),
                ],
                stop_reason="tool_use",
            ),
            faux_assistant_message(
                [
                    faux_text("Now I will edit it."),
                    faux_tool_call(
                        "replace_in_file",
                        {
                            "path": "model.py",
                            "old_text": "return x * 2",
                            "new_text": "return x * 3",
                        },
                        id="tc-2",
                    ),
                ],
                stop_reason="tool_use",
            ),
            faux_assistant_message("Done, edited model.py."),
        ]
    )

    async with SQLiteCheckpointer(str(app_config.db_path)) as cp:
        agent = build_agent(
            model=model,
            config=app_config,
            checkpointer=cp,
            thread_id="user:test-full",
            project_dir=project_dir,
            run_id="run-full",
        )
        channel = agent.channel

        async def host():
            await _await_pending(channel)
            req = channel.pending
            assert req is not None
            assert req.payload.kind == "approve"
            assert req.payload.tool_name == "replace_in_file"
            await channel.answer(req.question_id, ApproveAnswer(decision="approve"))

        task = asyncio.create_task(host())
        await agent.prompt("把 predict 的倍数改成 3", run_id="run-full")
        await task

        content = (project_dir / "model.py").read_text()
        assert "return x * 3" in content


async def test_ask_user_tool_available(app_config: AppConfig):
    """ask_user 工具在工具列表中（模型可主动提问）。"""
    model = _make_faux_model([faux_assistant_message("ok")])
    project_dir = app_config.projects_dir / "default"
    project_dir.mkdir(parents=True, exist_ok=True)
    async with SQLiteCheckpointer(str(app_config.db_path)) as cp:
        agent = build_agent(
            model=model,
            config=app_config,
            checkpointer=cp,
            thread_id="user:test-ask",
            project_dir=project_dir,
            run_id="run-ask",
        )
        names = {t.name for t in agent.state.tools}
        assert "ask_user" in names
        assert "read_file" in names
        assert "replace_in_file" in names
        assert "list_papers" in names
