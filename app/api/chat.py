"""聊天路由：SSE 流式消息、HITL 响应、中止、历史。

SSE 事件转换逻辑从 server.py 迁移至此。
"""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cubepi.agent.types import AgentEvent
from cubepi.hitl import HitlNoPendingRequest, HitlStaleAnswer

from app.services.chat_service import ChatService


class PromptBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class RespondBody(BaseModel):
    question_id: str
    decision: Literal["approve", "deny", "edit"]
    reason: str | None = None
    edited_args: dict | None = None


def _current_user_id() -> str:
    """认证占位：MVP 固定单用户。真实场景替换为 JWT/session 解码。"""
    return "demo-user"


def _jsonable(value: object) -> object:
    """把 pydantic 模型/列表递归转换为 JSON 可序列化对象。"""
    if isinstance(value, BaseModel):
        return value.model_dump()
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    return value


def _event_to_sse_dict(event: AgentEvent) -> dict:
    """把 agent 事件转换为 SSE 事件字典。"""
    from cubepi.agent.types import (
        AgentAbortedEvent,
        AgentEndEvent,
        AgentSuspendedEvent,
        HitlRequestEvent,
        MessageEndEvent,
        MessageUpdateEvent,
        ToolExecutionEndEvent,
        ToolExecutionStartEvent,
    )

    if isinstance(event, MessageUpdateEvent):
        if event.stream_event.type == "text_delta":
            return {"event": "delta", "data": event.stream_event.delta}
        if event.stream_event.type == "thinking_delta":
            return {"event": "thinking", "data": event.stream_event.delta}
        return {"event": "ignore", "data": ""}
    if isinstance(event, MessageEndEvent):
        # 若消息带错误（如 API key 无效），把错误展示给用户
        msg = event.message
        if getattr(msg, "stop_reason", None) == "error":
            err = getattr(msg, "error_message", None) or "模型调用失败"
            return {"event": "error", "data": json.dumps({"message": err})}
        return {"event": "ignore", "data": ""}
    if isinstance(event, ToolExecutionStartEvent):
        return {"event": "tool_start", "data": json.dumps({"name": event.tool_name})}
    if isinstance(event, ToolExecutionEndEvent):
        return {"event": "tool_end", "data": json.dumps({"name": event.tool_name})}
    if isinstance(event, HitlRequestEvent):
        payload = event.request.payload
        return {
            "event": "hitl_request",
            "data": json.dumps(
                {
                    "question_id": event.request.question_id,
                    "kind": payload.kind,
                    "tool_name": getattr(payload, "tool_name", None),
                    "args": getattr(payload, "args", None),
                    "details": getattr(payload, "details", None),
                    "prompt": getattr(payload, "prompt", None),
                    "questions": _jsonable(getattr(payload, "questions", None)),
                }
            ),
        }
    if isinstance(event, AgentEndEvent):
        return {"event": "done", "data": ""}
    if isinstance(event, AgentSuspendedEvent):
        return {"event": "suspended", "data": ""}
    if isinstance(event, AgentAbortedEvent):
        return {"event": "aborted", "data": ""}
    return {"event": "ignore", "data": ""}


def create_chat_router(chat_service: ChatService) -> APIRouter:
    """创建聊天路由（依赖注入 chat_service）。"""
    router = APIRouter(prefix="/projects/{project_id}/chat", tags=["chat"])

    @router.post("/{conversation_id}/messages")
    async def post_message(
        project_id: str, conversation_id: str, body: PromptBody
    ) -> EventSourceResponse:
        """发送消息，SSE 流式返回 agent 事件。

        若 agent 触发 HITL 确认（修改类工具），会先发出 hitl_request 事件，
        然后挂起（agent_suspended），前端收到后弹窗确认，再调 /respond。
        """
        try:
            queue, task = await chat_service.post_message(
                user_id=_current_user_id(),
                project_id=project_id,
                conversation_id=conversation_id,
                text=body.text,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return EventSourceResponse(_event_generator(queue, task))

    @router.post("/{conversation_id}/respond")
    async def respond(
        project_id: str, conversation_id: str, body: RespondBody
    ) -> EventSourceResponse:
        """回答 HITL 确认请求，恢复 agent 执行。"""
        try:
            queue, task = await chat_service.respond(
                user_id=_current_user_id(),
                project_id=project_id,
                conversation_id=conversation_id,
                question_id=body.question_id,
                decision=body.decision,
                reason=body.reason,
                edited_args=body.edited_args,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        except HitlNoPendingRequest:
            raise HTTPException(status_code=404, detail="no pending request")
        except HitlStaleAnswer:
            raise HTTPException(status_code=409, detail="stale answer")
        return EventSourceResponse(_event_generator(queue, task))

    @router.post("/{conversation_id}/abort")
    async def abort_run(project_id: str, conversation_id: str) -> dict:
        """中止当前 run / 关闭 pending 请求。"""
        try:
            await chat_service.abort(
                user_id=_current_user_id(),
                project_id=project_id,
                conversation_id=conversation_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"status": "aborted"}

    @router.get("/{conversation_id}/pending")
    async def get_pending(project_id: str, conversation_id: str) -> dict:
        """查询当前待确认请求（跨进程恢复场景用）。"""
        try:
            pending = await chat_service.get_pending(
                user_id=_current_user_id(),
                project_id=project_id,
                conversation_id=conversation_id,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"pending": pending}

    @router.get("/{conversation_id}/history")
    async def get_history(project_id: str, conversation_id: str) -> dict:
        """读取会话历史消息。"""
        messages = await chat_service.get_history(
            user_id=_current_user_id(),
            project_id=project_id,
            conversation_id=conversation_id,
        )
        return {"messages": messages}

    return router


async def _event_generator(queue: asyncio.Queue, task: asyncio.Task) -> AsyncIterator[dict]:
    """将一次 Agent 运行的事件转发为 SSE，包含 HITL 恢复阶段。"""
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            sse = _event_to_sse_dict(event)
            if sse["event"] != "ignore":
                yield sse
            if sse["event"] in {"done", "suspended", "aborted"}:
                break
    finally:
        await task
