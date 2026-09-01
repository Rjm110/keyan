"""项目（project）数据访问层。

项目元数据存储在 workspace/projects.json（JSON 文件）：
- 项目数量少、结构简单，JSON 比 DB 更直观易改
- 项目 = 用户电脑上真实存在的目录（path 字段记录绝对路径）
- 会话归属通过 thread_id 前缀（{user_id}:{project_id}:{conversation_id}）表达

原子写：tmp 文件 + replace（与 config.py 的 RuntimeConfig.save_to_file 一致）。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# 默认项目 ID（旧数据迁移目标）
DEFAULT_PROJECT_ID = "default"
# 项目 ID 前缀
_PROJECT_PREFIX = "proj_"


@dataclass
class Project:
    """项目元数据。"""

    id: str
    name: str
    path: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "path": self.path,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> Project:
        return cls(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            path=str(data.get("path", "")),
            created_at=float(data.get("created_at", 0.0)),
            updated_at=float(data.get("updated_at", 0.0)),
        )


def generate_project_id() -> str:
    """生成项目 ID：proj_ + 6 位十六进制。"""
    return f"{_PROJECT_PREFIX}{uuid.uuid4().hex[:6]}"


class ProjectRepository:
    """projects.json 的 CRUD。"""

    def __init__(self, path: Path) -> None:
        self._path = path

    def _load(self) -> list[Project]:
        """读取 projects.json；文件不存在/损坏返回空列表。"""
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        projects = data.get("projects", []) if isinstance(data, dict) else []
        if not isinstance(projects, list):
            return []
        return [Project.from_dict(p) for p in projects if isinstance(p, dict)]

    def _save(self, projects: list[Project]) -> None:
        """原子写 projects.json（tmp + replace）。"""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(
                {"projects": [p.to_dict() for p in projects]},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.chmod(tmp, 0o600)
        tmp.replace(self._path)

    def list(self) -> list[Project]:
        """列出所有项目（按创建时间升序）。"""
        return sorted(self._load(), key=lambda p: p.created_at)

    def get(self, project_id: str) -> Project | None:
        """按 ID 查找项目。"""
        for p in self._load():
            if p.id == project_id:
                return p
        return None

    def create(self, name: str, path: str) -> Project:
        """创建项目（写入 projects.json）。"""
        now = time.time()
        project = Project(
            id=generate_project_id(),
            name=name,
            path=path,
            created_at=now,
            updated_at=now,
        )
        projects = self._load()
        projects.append(project)
        self._save(projects)
        return project

    def create_default(self, name: str, path: str) -> Project:
        """创建默认项目（id 固定为 default，用于旧数据迁移）。"""
        now = time.time()
        project = Project(
            id=DEFAULT_PROJECT_ID,
            name=name,
            path=path,
            created_at=now,
            updated_at=now,
        )
        projects = self._load()
        projects.append(project)
        self._save(projects)
        return project

    def rename(self, project_id: str, name: str) -> Project | None:
        """重命名项目。"""
        projects = self._load()
        for p in projects:
            if p.id == project_id:
                p.name = name
                p.updated_at = time.time()
                self._save(projects)
                return p
        return None

    def update_path(self, project_id: str, path: str) -> Project | None:
        """更新项目路径（旧数据兼容：补上默认项目 path）。"""
        projects = self._load()
        for p in projects:
            if p.id == project_id:
                p.path = path
                p.updated_at = time.time()
                self._save(projects)
                return p
        return None

    def delete(self, project_id: str) -> bool:
        """从 projects.json 移除项目。"""
        projects = self._load()
        remaining = [p for p in projects if p.id != project_id]
        if len(remaining) == len(projects):
            return False
        self._save(remaining)
        return True
