"""科研助手 FastAPI 后端。

路由：
- POST /chat/{thread_id}/messages  — 发送消息，SSE 流式返回（含 HITL pending 事件）
- POST /chat/{thread_id}/respond   — 回答 HITL 确认（approve/deny/edit）
- POST /chat/{thread_id}/abort     — 中止当前 run / 关闭 pending
- GET  /chat/{thread_id}/pending   — 查询当前待确认请求
- GET  /chat/{thread_id}/history   — 会话历史
- GET  /papers                     — 论文目录列表
- GET  /baseline/tree              — baseline 文件树

架构（参考 examples/postgres_fastapi.py + website/docs/guides/hitl/durable.md）：
- 全局共享一个 SQLiteCheckpointer（单 worker 安全，asyncio.Lock 串行化）
- 每个请求新建 Agent 实例（轻量），thread_id 隔离会话
- HITL 两阶段：POST /messages 检测到 pending 后 detach() 返回
  {status: "awaiting_approval"}；前端确认后 POST /respond 恢复执行
"""

from __future__ import annotations

import asyncio
import json
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from cubepi.agent.types import AgentEvent
from cubepi.checkpointer.sqlite import SQLiteCheckpointer
from cubepi.hitl import ApproveAnswer, HitlNoPendingRequest, HitlStaleAnswer

from app.agent_factory import build_agent
from app.config import (
    PROVIDER_OPTIONS,
    AppConfig,
    build_model,
    get_runtime_config,
    load_config,
    set_runtime_config,
)

# 全局配置与 checkpointer（单 worker 共享）
_config: AppConfig = load_config()
_checkpointer: SQLiteCheckpointer | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global _checkpointer
    _checkpointer = SQLiteCheckpointer(str(_config.db_path))
    await _checkpointer.__aenter__()
    yield
    await _checkpointer.__aexit__(None, None, None)


app = FastAPI(title="科研助手", lifespan=lifespan)


# ---------- 请求/响应模型 ----------


class PromptBody(BaseModel):
    text: str = Field(min_length=1, max_length=20000)


class RespondBody(BaseModel):
    question_id: str
    decision: Literal["approve", "deny", "edit"]
    reason: str | None = None
    edited_args: dict | None = None


class ConfigBody(BaseModel):
    provider: str = Field(min_length=1)
    api_key: str = Field(min_length=1)
    model: str | None = None
    base_url: str | None = None


# ---------- 工具函数 ----------


def _thread_id(user_id: str, conversation_id: str) -> str:
    """多用户隔离：user_id 前缀 + conversation_id。"""
    return f"{user_id}:{conversation_id}"


def _current_user_id() -> str:
    """认证占位：MVP 固定单用户。真实场景替换为 JWT/session 解码。"""
    return "demo-user"


def _agent_events_to_sse(agent, queue: asyncio.Queue) -> None:
    """把 agent 事件桥接到 asyncio.Queue（SSE 生成器消费）。"""

    def listener(event: AgentEvent, signal=None) -> None:
        queue.put_nowait(event)

    agent.subscribe(listener)


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
                    "questions": getattr(payload, "questions", None),
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


# ---------- 路由 ----------


@app.post("/chat/{conversation_id}/messages")
async def post_message(conversation_id: str, body: PromptBody) -> EventSourceResponse:
    """发送消息，SSE 流式返回 agent 事件。

    若 agent 触发 HITL 确认（修改类工具），会先发出 hitl_request 事件，
    然后挂起（agent_suspended），前端收到后弹窗确认，再调 /respond。
    """
    if _checkpointer is None:
        raise HTTPException(status_code=503, detail="server not ready")
    thread_id = _thread_id(_current_user_id(), conversation_id)
    try:
        model = build_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    run_id = uuid.uuid4().hex
    agent = build_agent(
        model=model,
        config=_config,
        checkpointer=_checkpointer,
        thread_id=thread_id,
        run_id=run_id,
    )

    queue: asyncio.Queue = asyncio.Queue()
    _agent_events_to_sse(agent, queue)

    async def event_generator() -> AsyncIterator[dict]:
        task = asyncio.create_task(agent.prompt(body.text, run_id=run_id))
        try:
            while True:
                event = await queue.get()
                if event is None:
                    break
                sse = _event_to_sse_dict(event)
                if sse["event"] != "ignore":
                    yield sse
                # agent 结束（done）后关闭 SSE 流，否则浏览器 fetch 永不结束
                if sse["event"] == "done":
                    break
        finally:
            await task

    return EventSourceResponse(event_generator())


@app.post("/chat/{conversation_id}/respond")
async def respond(conversation_id: str, body: RespondBody) -> dict:
    """回答 HITL 确认请求，恢复 agent 执行。"""
    if _checkpointer is None:
        raise HTTPException(status_code=503, detail="server not ready")
    thread_id = _thread_id(_current_user_id(), conversation_id)
    try:
        model = build_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    agent = build_agent(
        model=model,
        config=_config,
        checkpointer=_checkpointer,
        thread_id=thread_id,
    )
    answer = ApproveAnswer(
        decision=body.decision,
        reason=body.reason,
        edited_args=body.edited_args,
    )
    try:
        await agent.respond(question_id=body.question_id, answer=answer)
    except HitlNoPendingRequest:
        raise HTTPException(status_code=404, detail="no pending request")
    except HitlStaleAnswer:
        raise HTTPException(status_code=409, detail="stale answer")
    return {"status": "ok"}


@app.post("/chat/{conversation_id}/abort")
async def abort_run(conversation_id: str) -> dict:
    """中止当前 run / 关闭 pending 请求。"""
    if _checkpointer is None:
        raise HTTPException(status_code=503, detail="server not ready")
    thread_id = _thread_id(_current_user_id(), conversation_id)
    try:
        model = build_model()
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    agent = build_agent(
        model=model,
        config=_config,
        checkpointer=_checkpointer,
        thread_id=thread_id,
    )
    await agent.abort_pending(reason="user aborted")
    return {"status": "aborted"}


@app.get("/chat/{conversation_id}/pending")
async def get_pending(conversation_id: str) -> dict:
    """查询当前待确认请求（跨进程恢复场景用）。"""
    if _checkpointer is None:
        raise HTTPException(status_code=503, detail="server not ready")
    thread_id = _thread_id(_current_user_id(), conversation_id)
    model = build_model()
    agent = build_agent(
        model=model,
        config=_config,
        checkpointer=_checkpointer,
        thread_id=thread_id,
    )
    pending = await agent.load_pending_hitl_request()
    if pending is None:
        return {"pending": None}
    payload = pending.payload
    return {
        "pending": {
            "question_id": pending.question_id,
            "kind": payload.kind,
            "tool_name": getattr(payload, "tool_name", None),
            "args": getattr(payload, "args", None),
            "details": getattr(payload, "details", None),
            "prompt": getattr(payload, "prompt", None),
            "questions": getattr(payload, "questions", None),
        }
    }


@app.get("/chat/{conversation_id}/history")
async def get_history(conversation_id: str) -> dict:
    """读取会话历史消息。"""
    if _checkpointer is None:
        raise HTTPException(status_code=503, detail="server not ready")
    thread_id = _thread_id(_current_user_id(), conversation_id)
    data = await _checkpointer.load(thread_id)
    if data is None:
        return {"messages": []}
    messages = []
    for msg in data.messages:
        messages.append(
            {
                "role": msg.role,
                "content": _message_to_text(msg),
            }
        )
    return {"messages": messages}


def _message_to_text(msg) -> str:
    """把 Message 转成纯文本（用于历史展示）。"""
    from cubepi.providers.base import TextContent

    if hasattr(msg, "content") and isinstance(msg.content, list):
        parts = [b.text for b in msg.content if isinstance(b, TextContent)]
        return "\n".join(parts)
    return str(msg)


@app.get("/config")
async def get_config() -> dict:
    """返回可用 provider 列表与当前配置状态（API key 脱敏）。"""
    runtime = get_runtime_config()
    return {
        "providers": PROVIDER_OPTIONS,
        "current": {
            "provider": runtime.provider,
            "model": runtime.model,
            "base_url": runtime.base_url,
            "configured": runtime.is_configured(),
            "api_key_masked": (
                f"{runtime.api_key[:4]}…{runtime.api_key[-4:]}"
                if runtime.api_key and len(runtime.api_key) > 8
                else "***"
                if runtime.api_key
                else None
            ),
        },
    }


@app.post("/config")
async def post_config(body: ConfigBody) -> dict:
    """保存前端提交的 provider 配置（内存存储）。"""
    valid_ids = {p["id"] for p in PROVIDER_OPTIONS}
    if body.provider not in valid_ids:
        raise HTTPException(status_code=400, detail=f"未知 provider：{body.provider}")
    set_runtime_config(
        provider=body.provider,
        api_key=body.api_key,
        model=body.model,
        base_url=body.base_url,
    )
    return {"status": "ok", "provider": body.provider}


@app.get("/papers")
async def list_papers() -> dict:
    """论文目录列表。"""
    papers = sorted(
        p.name for p in _config.papers_dir.iterdir() if p.suffix.lower() == ".pdf"
    )
    return {"papers": papers}


@app.get("/baseline/tree")
async def baseline_tree() -> dict:
    """baseline 文件树（两层，供前端展示）。"""
    root = _config.baseline_dir
    tree: list[dict] = []
    for child in sorted(root.iterdir()):
        if child.name.startswith("."):
            continue
        if child.is_dir():
            sub = sorted(p.name for p in child.iterdir() if not p.name.startswith("."))[
                :50
            ]
            tree.append({"name": child.name, "type": "dir", "children": sub})
        else:
            tree.append({"name": child.name, "type": "file"})
    return {"root": str(root), "tree": tree}


# 静态前端
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")
