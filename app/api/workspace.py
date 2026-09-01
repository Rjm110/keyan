"""工作区路由：论文目录、项目代码文件树。

- GET /papers                    — 论文目录列表
- GET /projects/{project_id}/baseline/tree — 项目代码文件树
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.workspace_service import WorkspaceService


def create_workspace_router(workspace_service: WorkspaceService) -> APIRouter:
    """创建工作区路由（依赖注入 workspace_service）。"""
    router = APIRouter(tags=["workspace"])

    @router.get("/papers")
    async def list_papers() -> dict:
        """论文目录列表。"""
        return {"papers": workspace_service.list_papers()}

    @router.get("/projects/{project_id}/baseline/tree")
    async def baseline_tree(project_id: str) -> dict:
        """项目代码文件树（两层，供前端展示）。"""
        return workspace_service.baseline_tree(project_id)

    return router
