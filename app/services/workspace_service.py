"""工作区业务逻辑：论文目录、项目代码文件树。

从 server.py 迁移而来，职责：
- 读取文件系统（论文 PDF 列表、项目代码树）
- 不感知 HTTP
"""

from __future__ import annotations

from app.config import AppConfig
from app.services.project_service import ProjectService


class WorkspaceService:
    """工作区（论文 / 项目代码）业务逻辑。"""

    def __init__(self, config: AppConfig, project_service: ProjectService) -> None:
        self._config = config
        self._project_service = project_service

    def list_papers(self) -> list[str]:
        """论文目录列表（PDF 文件名，排序）。"""
        return sorted(
            p.name
            for p in self._config.papers_dir.iterdir()
            if p.suffix.lower() == ".pdf"
        )

    def baseline_tree(self, project_id: str) -> dict:
        """项目代码文件树（两层，供前端展示）。"""
        root = self._project_service.project_dir(project_id)
        if not root.exists():
            return {"root": str(root), "tree": []}
        tree: list[dict] = []
        for child in sorted(root.iterdir()):
            if child.name.startswith("."):
                continue
            if child.is_dir():
                sub = sorted(
                    p.name for p in child.iterdir() if not p.name.startswith(".")
                )[:50]
                tree.append({"name": child.name, "type": "dir", "children": sub})
            else:
                tree.append({"name": child.name, "type": "file"})
        return {"root": str(root), "tree": tree}
