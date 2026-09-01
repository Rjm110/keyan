"""api 层：HTTP 路由。

职责：
- 只做 HTTP 适配（请求解析、响应序列化、SSE 转换）
- 业务逻辑在 services 层，数据访问在 repositories 层
- 依赖注入：create_api_router(checkpointer, config) 显式传入依赖
"""

from __future__ import annotations

from fastapi import APIRouter

from cubepi.checkpointer.base import Checkpointer

from app.config import AppConfig
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import ProjectRepository
from app.services.chat_service import ChatService
from app.services.conversation_service import ConversationService
from app.services.project_service import ProjectService
from app.services.workspace_service import WorkspaceService

from app.api.chat import create_chat_router
from app.api.config import create_config_router
from app.api.conversations import create_conversations_router
from app.api.projects import create_projects_router
from app.api.workspace import create_workspace_router


def create_api_router(
    checkpointer: Checkpointer,
    config: AppConfig,
) -> APIRouter:
    """装配 API 路由（依赖注入入口）。

    所有 service/repository 在此构造并注入，路由层不感知具体实现。
    """
    # repositories
    conversation_repo = ConversationRepository(checkpointer)
    project_repo = ProjectRepository(config.projects_json_path)

    # services
    project_service = ProjectService(
        project_repo, config.projects_dir, conversation_repo
    )
    conversation_service = ConversationService(conversation_repo)
    chat_service = ChatService(
        config, checkpointer, conversation_service, project_service
    )
    workspace_service = WorkspaceService(config, project_service)

    router = APIRouter()
    router.include_router(create_chat_router(chat_service))
    router.include_router(create_conversations_router(conversation_service))
    router.include_router(create_projects_router(project_service))
    router.include_router(create_config_router())
    router.include_router(create_workspace_router(workspace_service))

    # 全量会话列表（不带 project_id 前缀），供前端按项目分组渲染
    @router.get("/conversations")
    async def list_all_conversations() -> dict:
        """列出全部会话（按更新时间倒序，含 project_id 字段）。"""
        conversations = await conversation_service.list_conversations()
        return {"conversations": conversations}

    return router


__all__ = ["create_api_router"]
