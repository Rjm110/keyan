"""聊天业务逻辑：消息发送、HITL 响应、中止、历史读取。

从 server.py 迁移而来，职责：
- 编排 Agent 构建与事件流（SSE 转换在 api 层）
- 不感知 HTTP 细节（SSE 事件字典由 api 层负责）
- 会话归属项目：thread_id = {user_id}:{project_id}:{conversation_id}
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any, Literal

from cubepi.checkpointer.base import Checkpointer
from cubepi.hitl import ApproveAnswer

from app.agent_factory import build_agent
from app.config import AppConfig, build_model
from app.repositories.project_repo import DEFAULT_PROJECT_ID
from app.services.conversation_service import ConversationService
from app.services.project_service import ProjectService


class ChatService:
    """聊天业务逻辑。"""

    def __init__(
        self,
        config: AppConfig,
        checkpointer: Checkpointer,
        conversation_service: ConversationService,
        project_service: ProjectService,
    ) -> None:
        self._config = config
        self._checkpointer = checkpointer
        self._conversation_service = conversation_service
        self._project_service = project_service

    # ---------- 工具 ----------

    def _thread_id(self, user_id: str, project_id: str, conversation_id: str) -> str:
        """多用户 + 多项目隔离：user_id:project_id:conversation_id。"""
        return f"{user_id}:{project_id}:{conversation_id}"

    async def _resolve_thread_id(
        self, user_id: str, project_id: str, conversation_id: str
    ) -> str:
        """解析实际 thread_id：3 段优先，旧 2 段格式兜底（default 项目兼容）。

        旧数据（项目化改造前）的 thread_id 是 user_id:conversation_id 两段，
        属于 default 项目。读取/写入时若 3 段不存在而 2 段存在，
        则继续使用 2 段，保证旧会话数据连续。
        """
        three = self._thread_id(user_id, project_id, conversation_id)
        if project_id == DEFAULT_PROJECT_ID:
            legacy = f"{user_id}:{conversation_id}"
            if (
                await self._checkpointer.load(three) is None
                and await self._checkpointer.load(legacy) is not None
            ):
                return legacy
        return three

    def _build_agent(self, thread_id: str, project_id: str, run_id: str | None = None):
        """构建 Agent 实例（轻量，每请求新建）。

        agent 沙箱根 = 当前项目目录（workspace/projects/<id>/），
        只能读写当前项目代码，不能跨项目。
        """
        model = build_model()
        project_dir = self._project_service.project_dir(project_id)
        return build_agent(
            model=model,
            config=self._config,
            checkpointer=self._checkpointer,
            thread_id=thread_id,
            project_dir=project_dir,
            run_id=run_id,
        )

    # ---------- 核心操作 ----------

    async def post_message(
        self,
        user_id: str,
        project_id: str,
        conversation_id: str,
        text: str,
    ) -> tuple[asyncio.Queue, asyncio.Task]:
        """发送消息，返回 (事件队列, agent 任务)。

        调用方（api 层）消费队列并转换为 SSE。

        HITL 挂起处理：agent 触发确认（修改类工具）时，channel future 挂起，
        原始 prompt task 永不结束。这里在检测到 pending 后调用 agent.detach()
        让原始 run 正常结束（发出 AgentSuspendedEvent），SSE 流随之关闭；
        用户确认后由 respond() 用新 agent 实例恢复执行。
        """
        thread_id = await self._resolve_thread_id(
            user_id, project_id, conversation_id
        )
        run_id = uuid.uuid4().hex

        # 首条消息自动生成会话标题（先于 agent 构建，确保即使模型未配置也会落库）
        await self._conversation_service.ensure_title(thread_id, text)

        agent = self._build_agent(thread_id, project_id, run_id)

        queue: asyncio.Queue = asyncio.Queue()
        agent.subscribe(lambda event, signal=None: queue.put_nowait(event))
        task = asyncio.create_task(agent.prompt(text, run_id=run_id))

        # 检测 HITL pending：一旦挂起立即 detach，让原始 task 正常结束。
        # 轮询而非订阅事件，避免与 SSE 消费方竞争队列。
        async def _watch_hitl() -> None:
            load_pending = getattr(self._checkpointer, "load_pending", None)
            if load_pending is None:
                return
            try:
                while not task.done():
                    if await load_pending(thread_id) is not None:
                        await agent.detach()
                        return
                    await asyncio.sleep(0.05)
            except asyncio.CancelledError:
                pass

        watcher = asyncio.create_task(_watch_hitl())
        task.add_done_callback(lambda _t: watcher.cancel())
        return queue, task

    async def respond(
        self,
        user_id: str,
        project_id: str,
        conversation_id: str,
        question_id: str,
        decision: Literal["approve", "deny", "edit"],
        reason: str | None = None,
        edited_args: dict | None = None,
    ) -> tuple[asyncio.Queue, asyncio.Task]:
        """回答 HITL 确认请求，恢复 agent 执行。

        关键：必须先从 checkpointer 恢复 pending 的 run_id 并传给
        _build_agent，否则 CheckpointedChannel 的 run_id=None，
        agent.respond() 的 _validate_hitl_bindings 会抛 ValueError（500）。
        """
        thread_id = await self._resolve_thread_id(
            user_id, project_id, conversation_id
        )
        # 恢复 pending 请求的 run_id（与 post_message 时绑定的一致）
        load_pending = getattr(self._checkpointer, "load_pending", None)
        run_id: str | None = None
        if load_pending is not None:
            loaded = await load_pending(thread_id)
            if loaded is not None:
                run_id = loaded[1]
        agent = self._build_agent(thread_id, project_id, run_id)
        answer = ApproveAnswer(
            decision=decision,
            reason=reason,
            edited_args=edited_args,
        )
        queue: asyncio.Queue = asyncio.Queue()
        agent.subscribe(lambda event, signal=None: queue.put_nowait(event))
        task = asyncio.create_task(
            agent.respond(question_id=question_id, answer=answer)
        )
        return queue, task

    async def abort(self, user_id: str, project_id: str, conversation_id: str) -> None:
        """中止当前 run / 关闭 pending 请求。"""
        thread_id = await self._resolve_thread_id(
            user_id, project_id, conversation_id
        )
        agent = self._build_agent(thread_id, project_id)
        await agent.abort_pending(reason="user aborted")

    async def get_pending(
        self, user_id: str, project_id: str, conversation_id: str
    ) -> dict | None:
        """查询当前待确认请求（跨进程恢复场景用）。"""
        thread_id = await self._resolve_thread_id(
            user_id, project_id, conversation_id
        )
        agent = self._build_agent(thread_id, project_id)
        pending = await agent.load_pending_hitl_request()
        if pending is None:
            return None
        payload = pending.payload
        return {
            "question_id": pending.question_id,
            "kind": payload.kind,
            "tool_name": getattr(payload, "tool_name", None),
            "args": getattr(payload, "args", None),
            "details": getattr(payload, "details", None),
            "prompt": getattr(payload, "prompt", None),
            "questions": getattr(payload, "questions", None),
        }

    async def get_history(
        self, user_id: str, project_id: str, conversation_id: str
    ) -> list[dict]:
        """读取会话历史消息。"""
        thread_id = await self._resolve_thread_id(
            user_id, project_id, conversation_id
        )
        messages = await self._checkpointer.load(thread_id)
        if messages is None:
            return []
        return [
            {"role": msg.role, "content": _message_to_text(msg)}
            for msg in messages.messages
        ]


def _message_to_text(msg: Any) -> str:
    """把 Message 转成纯文本（用于历史展示）。"""
    from cubepi.providers.base import TextContent

    if hasattr(msg, "content") and isinstance(msg.content, list):
        parts = [b.text for b in msg.content if isinstance(b, TextContent)]
        return "\n".join(parts)
    return str(msg)
