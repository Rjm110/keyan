"""项目路由：列表、创建、重命名、删除、目录浏览。

- GET    /projects — 项目列表
- POST   /projects — 创建项目（body: {name, path}，path 为真实目录）
- PATCH  /projects/{project_id} — 重命名项目（body: {name}）
- DELETE /projects/{project_id} — 删除项目（只移除记录，不删磁盘代码）
- GET    /projects/browse?path=... — 目录浏览（"我的电脑"式选择器）
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.services.project_service import ProjectService


class ProjectBody(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    path: str = Field(min_length=1, max_length=1024)


class RenameBody(BaseModel):
    name: str = Field(min_length=1, max_length=50)


def create_projects_router(project_service: ProjectService) -> APIRouter:
    """创建项目路由（依赖注入 project_service）。"""
    router = APIRouter(prefix="/projects", tags=["projects"])

    @router.get("")
    async def list_projects() -> dict:
        """项目列表。"""
        return {"projects": project_service.list_projects()}

    @router.get("/browse")
    async def browse(path: str | None = Query(default=None)) -> dict:
        """目录浏览：返回当前路径、父路径、子目录列表。"""
        try:
            return project_service.browse(path)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.post("")
    async def create_project(body: ProjectBody) -> dict:
        """创建项目（path 必须为真实存在的目录）。"""
        try:
            project = project_service.create_project(body.name.strip(), body.path.strip())
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"project": project}

    @router.patch("/{project_id}")
    async def rename_project(project_id: str, body: RenameBody) -> dict:
        """重命名项目。"""
        project = project_service.rename_project(project_id, body.name.strip())
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return {"project": project}

    @router.delete("/{project_id}")
    async def delete_project(project_id: str) -> dict:
        """删除项目（只移除记录 + 会话，不删磁盘代码）。"""
        deleted = await project_service.delete_project(
            user_id="demo-user",
            project_id=project_id,
        )
        if not deleted:
            raise HTTPException(status_code=404, detail="project not found")
        return {"status": "deleted"}

    return router
