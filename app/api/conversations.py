"""会话路由：列表、创建、删除。

- GET    /projects/{project_id}/conversations — 会话列表（按更新时间倒序）
- POST   /projects/{project_id}/conversations — 新建会话（懒创建，仅生成 ID）
- DELETE /projects/{project_id}/conversations/{conversation_id} — 删除会话（幂等）
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.conversation_service import ConversationService


def create_conversations_router(
    conversation_service: ConversationService,
) -> APIRouter:
    """创建会话路由（依赖注入 conversation_service）。"""
    router = APIRouter(
        prefix="/projects/{project_id}/conversations", tags=["conversations"]
    )

    @router.get("")
    async def list_conversations(project_id: str) -> dict:
        """列出项目下所有会话（按更新时间倒序），供前端侧栏展示。"""
        conversations = await conversation_service.list_conversations(project_id)
        return {"conversations": conversations}

    @router.post("")
    async def create_conversation(project_id: str) -> dict:
        """新建会话（懒创建：仅生成 ID，第一条消息时才落库）。"""
        conversation = await conversation_service.create_conversation()
        return {"conversation": conversation}

    @router.delete("/{conversation_id}")
    async def delete_conversation(project_id: str, conversation_id: str) -> dict:
        """删除会话及其全部数据（幂等）。"""
        await conversation_service.delete_conversation(
            user_id="demo-user",
            project_id=project_id,
            conversation_id=conversation_id,
        )
        return {"status": "deleted"}

    return router
