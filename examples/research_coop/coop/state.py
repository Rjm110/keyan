"""项目状态仓：ProjectState 的唯一持有者 + 持久化预留缝。

持久化后端目前刻意没有实现。``ProjectStorage`` 协议就是预留的接缝，
将来接入 JSONL / SQLite 后端时，无需改动编排器与角色层。
"""

from __future__ import annotations

from typing import Protocol

from coop.types import ProjectState


class ProjectStorage(Protocol):
    """持久化后端契约（预留）。

    实现类必须能保存并加载完整的项目状态。
    """

    def save(self, state: ProjectState) -> None: ...

    def load(self) -> ProjectState | None: ...


class InMemoryStorage:
    """空后端：不保留任何数据（用于演示与测试）。"""

    def save(self, state: ProjectState) -> None:
        del state

    def load(self) -> ProjectState | None:
        return None


class ProjectStore:
    """持有实时 ProjectState，并经由存储后端提交落盘。"""

    def __init__(
        self,
        project: ProjectState,
        *,
        storage: ProjectStorage | None = None,
    ) -> None:
        self._project = project
        self._storage: ProjectStorage = storage or InMemoryStorage()

    @property
    def project(self) -> ProjectState:
        """实时、可变的项目状态（内部使用）。"""
        return self._project

    def snapshot(self) -> ProjectState:
        """深拷贝快照，供只读消费方使用（Agent、测试、前端）。"""
        return self._project.model_copy(deep=True)

    def commit(self) -> None:
        """持久化当前状态；在接入后端之前是廉价的无操作。"""
        self._storage.save(self._project)
