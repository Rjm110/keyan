"""基于 CubePi 的科研协作骨架。

两个角色 Agent（coder + researcher）由确定性编排器协调。共享状态定义在
:mod:`coop.types`，由 :class:`coop.state.ProjectStore` 持有；
目前尚未接入任何工具与持久化。
"""

from coop.orchestrator import ContextInjector, ResearchOrchestrator
from coop.roles import make_coder_agent, make_researcher_agent, role_prompt
from coop.state import ProjectStore
from coop.types import (
    AgentMessage,
    Artifact,
    BaselineSpec,
    PaperRef,
    ProjectState,
    Role,
    Task,
    TaskStatus,
)

__all__ = [
    "AgentMessage",
    "Artifact",
    "BaselineSpec",
    "ContextInjector",
    "PaperRef",
    "ProjectState",
    "ProjectStore",
    "ResearchOrchestrator",
    "Role",
    "Task",
    "TaskStatus",
    "make_coder_agent",
    "make_researcher_agent",
    "role_prompt",
]
