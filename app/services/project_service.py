"""项目业务逻辑：列表、创建、重命名、删除、默认项目迁移、目录浏览。

设计决策：
- 项目 = 用户电脑上真实存在的目录（path 字段记录绝对路径）
- 默认项目（id=default）：启动时自动创建，指向 workspace/projects/default，
  并把旧 workspace/baseline/ 内容迁移进去
- 删除项目：只移除元数据 + 项目下所有会话，**不删除磁盘上的代码目录**
- 会话归属：thread_id = {user_id}:{project_id}:{conversation_id}
"""

from __future__ import annotations

import shutil
from pathlib import Path

from app.repositories.conversation_repo import ConversationRepository
from app.repositories.project_repo import (
    DEFAULT_PROJECT_ID,
    ProjectRepository,
)

# 默认项目显示名
_DEFAULT_PROJECT_NAME = "默认项目"
# 目录浏览时隐藏的目录（除隐藏目录外，还隐藏这些常见敏感/大目录）
_BROWSE_HIDDEN = {"node_modules", "__pycache__", ".idea", ".vscode"}


class ProjectService:
    """项目业务逻辑。"""

    def __init__(
        self,
        repo: ProjectRepository,
        projects_dir: Path,
        conversation_repo: ConversationRepository,
    ) -> None:
        self._repo = repo
        self._projects_dir = projects_dir
        self._conversation_repo = conversation_repo

    # ---------- 目录 ----------

    def project_dir(self, project_id: str) -> Path:
        """项目代码目录（真实路径，来自 projects.json 的 path 字段）。"""
        project = self._repo.get(project_id)
        if project is None or not project.path:
            # 兜底：旧数据无 path 时回退到 projects/<id>/
            return self._projects_dir / project_id
        return Path(project.path).expanduser().resolve()

    # ---------- 迁移 ----------

    def ensure_default_project(self, legacy_baseline_dir: Path) -> None:
        """确保默认项目存在；首次启动时迁移旧 baseline 内容。

        幂等：projects.json 已存在 default 项目则跳过。
        兼容：旧数据 default 项目 path 为空时，补上 projects/default 路径。
        """
        existing = self._repo.get(DEFAULT_PROJECT_ID)
        if existing is not None:
            # 旧数据兼容：path 为空时补上默认路径
            if not existing.path:
                target = self._projects_dir / DEFAULT_PROJECT_ID
                target.mkdir(parents=True, exist_ok=True)
                self._repo.update_path(DEFAULT_PROJECT_ID, str(target))
            return
        target = self._projects_dir / DEFAULT_PROJECT_ID
        target.mkdir(parents=True, exist_ok=True)
        self._repo.create_default(_DEFAULT_PROJECT_NAME, str(target))
        # 迁移旧 baseline 内容（仅当 baseline 目录存在且有内容）
        if legacy_baseline_dir.is_dir() and any(legacy_baseline_dir.iterdir()):
            for child in legacy_baseline_dir.iterdir():
                dest = target / child.name
                if child.is_dir():
                    shutil.copytree(child, dest, dirs_exist_ok=True)
                else:
                    shutil.copy2(child, dest)

    # ---------- CRUD ----------

    def list_projects(self) -> list[dict]:
        """列出所有项目（含真实路径）。"""
        projects = self._repo.list()
        return [
            {
                "id": p.id,
                "name": p.name,
                "path": p.path,
                "created_at": p.created_at,
                "updated_at": p.updated_at,
            }
            for p in projects
        ]

    def create_project(self, name: str, path: str) -> dict:
        """创建项目（元数据 + 校验路径存在）。

        项目 = 用户电脑上真实存在的目录。path 必须存在且是目录。
        """
        project_path = Path(path).expanduser().resolve()
        if not project_path.is_dir():
            raise ValueError(f"目录不存在：{path}")
        project = self._repo.create(name, str(project_path))
        return project.to_dict()

    def rename_project(self, project_id: str, name: str) -> dict | None:
        """重命名项目。"""
        project = self._repo.rename(project_id, name)
        return project.to_dict() if project else None

    async def delete_project(self, user_id: str, project_id: str) -> bool:
        """删除项目：移除元数据 + 项目下所有会话。

        注意：**不删除磁盘上的代码目录**（codex 式，只移除记录）。
        """
        # 删除项目下所有会话（thread_id 前缀匹配）
        threads = await self._conversation_repo.list_threads()
        prefix = f"{user_id}:{project_id}:"
        for t in threads:
            if t.thread_id.startswith(prefix):
                await self._conversation_repo.delete(t.thread_id)
        # 从 projects.json 移除（不删代码目录）
        return self._repo.delete(project_id)

    # ---------- 目录浏览（"我的电脑"式选择器） ----------

    def browse(self, path: str | None = None) -> dict:
        """浏览目录：返回当前路径、父路径、子目录列表。

        path 为空时返回根目录（/ 或当前用户主目录）。
        """
        if path:
            current = Path(path).expanduser().resolve()
        else:
            current = Path.home()
        if not current.is_dir():
            raise ValueError(f"目录不存在：{current}")
        entries: list[dict] = []
        for child in sorted(current.iterdir()):
            if not child.is_dir():
                continue
            if child.name.startswith(".") or child.name in _BROWSE_HIDDEN:
                continue
            entries.append({"name": child.name, "path": str(child)})
        parent = str(current.parent) if current.parent != current else None
        return {
            "path": str(current),
            "parent": parent,
            "entries": entries,
        }

    # ---------- 会话归属 ----------

    def thread_id(self, user_id: str, project_id: str, conversation_id: str) -> str:
        """构造带项目段的 thread_id。"""
        return f"{user_id}:{project_id}:{conversation_id}"

    def project_id_from_thread(self, thread_id: str) -> str:
        """从 thread_id 提取项目 ID；旧格式（无项目段）视为 default。"""
        parts = thread_id.split(":")
        if len(parts) >= 3:
            return parts[1]
        return DEFAULT_PROJECT_ID
