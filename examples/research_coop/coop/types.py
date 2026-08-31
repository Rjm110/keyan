"""科研协作骨架的共享数据模型。

全部是纯 pydantic 模型，不做 I/O、不依赖 Agent 逻辑——是整个项目
"长什么样"的唯一事实来源。骨架里的其余部分（角色、编排器、状态仓）都
基于这些类型工作。
"""

from __future__ import annotations

import time
import uuid
from enum import Enum

from pydantic import BaseModel, Field


class Role(str, Enum):
    """参与科研项目的 Agent 角色。"""

    CODER = "coder"
    RESEARCHER = "researcher"


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class Task(BaseModel):
    """分配给单个角色 Agent 的一个工作单元。"""

    id: str = Field(default_factory=lambda: _new_id("task"))
    role: Role
    title: str
    prompt: str
    status: TaskStatus = TaskStatus.PENDING
    result: str | None = None
    error: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)


class PaperRef(BaseModel):
    """研究员 Agent 找到并整理的一篇论文。"""

    id: str = Field(default_factory=lambda: _new_id("paper"))
    title: str
    url: str = ""
    authors: list[str] = Field(default_factory=list)
    abstract: str = ""
    notes: str = ""


class Artifact(BaseModel):
    """工作区中产出的结果（代码、报告、数据、图表等）。"""

    id: str = Field(default_factory=lambda: _new_id("artifact"))
    name: str
    kind: str  # 例如 "code"、"report"、"data"、"figure"
    path: str = ""  # 产出后的工作区相对路径
    description: str = ""


class AgentMessage(BaseModel):
    """角色 Agent 的一轮回复记录，按项目顺序保存。"""

    id: str = Field(default_factory=lambda: _new_id("msg"))
    role: Role
    task_id: str
    content: str
    timestamp: float = Field(default_factory=time.time)


class BaselineSpec(BaseModel):
    """编码 Agent 要验证的上传 baseline。"""

    name: str
    source_path: str
    description: str = ""


class ProjectState(BaseModel):
    """科研协作项目所知道的全部信息。

    领域逻辑刻意保持小巧且无副作用，便于持久化、比对与单独测试。
    变更方法只改内存中的模型；落盘职责属于 ``coop.state.ProjectStore``。
    """

    name: str
    research_question: str
    baseline: BaselineSpec | None = None
    tasks: list[Task] = Field(default_factory=list)
    papers: list[PaperRef] = Field(default_factory=list)
    artifacts: list[Artifact] = Field(default_factory=list)
    messages: list[AgentMessage] = Field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 10

    def next_pending_task(self) -> Task | None:
        """返回最旧的一个 pending 任务；队列为空时返回 None。"""
        for task in self.tasks:
            if task.status == TaskStatus.PENDING:
                return task
        return None

    def start_task(self, task: Task) -> None:
        task.status = TaskStatus.RUNNING
        task.updated_at = time.time()

    def record_result(
        self,
        task: Task,
        result: str,
        *,
        error: str | None = None,
    ) -> None:
        task.status = TaskStatus.FAILED if error else TaskStatus.DONE
        task.result = result
        task.error = error
        task.updated_at = time.time()

    def record_message(self, *, role: Role, task_id: str, content: str) -> None:
        self.messages.append(AgentMessage(role=role, task_id=task_id, content=content))

    def add_paper(self, paper: PaperRef) -> None:
        self.papers.append(paper)

    def add_artifact(self, artifact: Artifact) -> None:
        self.artifacts.append(artifact)

    def context_snapshot(self, max_tasks: int = 12) -> str:
        """渲染一段紧凑的文本快照，供注入到各 Agent 的上下文。"""
        lines = [
            f"Project: {self.name}",
            f"Research question: {self.research_question}",
            f"Iteration: {self.iteration}/{self.max_iterations}",
        ]
        if self.baseline is not None:
            lines.append(
                f"Baseline: {self.baseline.name} at {self.baseline.source_path}"
            )
        if self.tasks:
            lines.append("Tasks:")
            for task in self.tasks[-max_tasks:]:
                lines.append(
                    f"  - [{task.status.value}] {task.title} ({task.role.value})"
                )
        lines.append(f"Papers collected: {len(self.papers)}")
        lines.append(f"Artifacts produced: {len(self.artifacts)}")
        return "\n".join(lines)
