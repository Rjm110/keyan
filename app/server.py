"""科研助手 FastAPI 入口（薄入口）。

职责：
- 创建 app + lifespan（初始化 checkpointer）
- 装配 API 路由（create_api_router 依赖注入）
- 挂载静态前端

架构分层：
- api/       — HTTP 路由（请求解析、SSE 转换）
- services/  — 业务逻辑（聊天、会话、工作区）
- repositories/ — 数据访问（Checkpointer CRUD 封装）
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from cubepi.checkpointer.sqlite import SQLiteCheckpointer

from app.api import create_api_router
from app.config import load_config, load_runtime_config_from_disk
from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import ProjectRepository
from app.services.project_service import ProjectService

# 全局配置与 checkpointer（单 worker 共享）
# SQLiteCheckpointer.__init__ 不连接数据库，__aenter__ 才连接
_config = load_config()
_checkpointer = SQLiteCheckpointer(str(_config.db_path))

# 启动时从磁盘加载持久化的运行时配置（workspace/config.json）
load_runtime_config_from_disk()

# 确保默认项目存在（首次启动迁移旧 baseline 内容）
_project_repo = ProjectRepository(_config.projects_json_path)
_project_service = ProjectService(
    _project_repo, _config.projects_dir, ConversationRepository(_checkpointer)
)
_project_service.ensure_default_project(_config.baseline_dir)


@asynccontextmanager
async def lifespan(_: FastAPI):
    await _checkpointer.__aenter__()
    yield
    await _checkpointer.__aexit__(None, None, None)


app = FastAPI(title="科研助手", lifespan=lifespan)


# 装配 API 路由（依赖注入：checkpointer + config）
app.include_router(create_api_router(_checkpointer, _config))


# 静态前端
app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).parent / "static"),
    name="static",
)


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(Path(__file__).parent / "static" / "index.html")
