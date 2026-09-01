"""ChatService HITL respond 回归测试：run_id 恢复。

覆盖 bug：post_message 传 run_id 绑定 CheckpointedChannel，
但 respond 未恢复 run_id → agent.respond() 的 _validate_hitl_bindings
抛 ValueError（HTTP 500）。修复后 respond 先从 checkpointer
恢复 pending 的 run_id 再构建 agent。
"""

from __future__ import annotations

import asyncio

from cubepi.checkpointer.sqlite import SQLiteCheckpointer
from cubepi.providers.faux import (
    FauxProvider,
    faux_assistant_message,
    faux_text,
    faux_tool_call,
)

from app.config import AppConfig
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import ProjectRepository
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.project_service import ProjectService


def _make_faux_model(responses):
    provider = FauxProvider(provider_id="faux")
    provider.set_responses(responses)
    return provider.model("faux-model")


async def _wait_pending(cp: SQLiteCheckpointer, thread_id: str, *, timeout: float = 2.0):
    """等待 pending 请求落库。"""

    async def _wait():
        while True:
            if await cp.load_pending(thread_id) is not None:
                return
            await asyncio.sleep(0)

    try:
        await asyncio.wait_for(_wait(), timeout=timeout)
    except asyncio.TimeoutError as exc:
        raise AssertionError(
            f"pending request did not appear within {timeout}s"
        ) from exc


async def test_respond_recovers_run_id(app_config: AppConfig, monkeypatch):
    """post_message 触发 HITL pending → respond 恢复 run_id → 不再 500。"""
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
    # ChatService._build_agent 内部调用 build_model()，monkeypatch 成 FauxProvider
    monkeypatch.setattr(
        "app.services.chat_service.build_model", lambda: model
    )

    async with SQLiteCheckpointer(str(app_config.db_path)) as cp:
        repo = ProjectRepository(app_config.projects_json_path)
        project_service = ProjectService(
            repo, app_config.projects_dir, ConversationRepository(cp)
        )
        conversation_service = ConversationService(
            ConversationRepository(cp)
        )
        service = ChatService(
            config=app_config,
            checkpointer=cp,
            conversation_service=conversation_service,
            project_service=project_service,
        )

        user_id, project_id, conversation_id = "u1", "default", "c1"
        thread_id = f"{user_id}:{project_id}:{conversation_id}"

        # 1. post_message：触发 HITL pending（run_id 绑定在 channel 上）
        queue, task = await service.post_message(
            user_id, project_id, conversation_id, "把 x 改成 2"
        )
        await _wait_pending(cp, thread_id)

        # 2. 读取 pending 的 question_id
        loaded = await cp.load_pending(thread_id)
        assert loaded is not None
        req, run_id = loaded
        assert run_id is not None, "pending 必须记录 run_id"

        # 3. respond：不显式传 run_id，验证 service 内部恢复
        await service.respond(
            user_id,
            project_id,
            conversation_id,
            question_id=req.question_id,
            decision="approve",
        )
        await task

        # 4. 工具已执行（approve 生效）
        content = (project_dir / "model.py").read_text()
        assert "x = 2" in content
        # pending 已清空
        assert await cp.load_pending(thread_id) is None