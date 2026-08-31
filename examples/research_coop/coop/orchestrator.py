"""确定性科研编排器（v1）。

一个朴素的异步 while 循环，与 CubePi 自带的 Agent 循环一脉相承：
规划 -> 派发 -> 收集 -> 决策。调度采用任务队列顺序，暂时没有 LLM 规划器
（那是后续可插拔的一步）。所有共享状态都放在 ProjectStore 里；角色 Agent
除了编排器注入的内容外保持无状态。
"""

from __future__ import annotations

import asyncio
import logging

from cubepi import Agent
from cubepi.middleware.base import Middleware
from cubepi.providers.base import AssistantMessage, TextContent

from coop.state import ProjectStore
from coop.types import ProjectState, Role, Task

logger = logging.getLogger(__name__)


class ContextInjector(Middleware):
    """在每次模型调用时，把一份紧凑的项目状态快照追加到系统提示词。

    这是框架的共享上下文机制：每个角色 Agent 都能看到整个项目的全貌
    （任务队列、论文、产物、迭代数），但都不持有它。
    """

    def __init__(self, store: ProjectStore) -> None:
        self._store = store

    async def transform_system_prompt(
        self,
        system_prompt: str,
        *,
        ctx: object,
        signal: asyncio.Event | None = None,
    ) -> str:
        del ctx, signal
        snapshot = self._store.project.context_snapshot()
        return f"{system_prompt}\n\n--- Shared project state ---\n{snapshot}"


def _assistant_text(agent: Agent) -> str:
    """提取 prompt() 调用后 Agent 的最终回复文本。

    ``Agent.prompt`` 返回的是 run id 而非回复；provider 的失败也不会抛异常，
    而是记录在最后一条消息的 ``error_message`` 上。
    """
    messages = agent.state.messages
    if not messages:
        return ""
    last = messages[-1]
    if not isinstance(last, AssistantMessage):
        return ""
    if last.error_message:
        raise RuntimeError(last.error_message)
    parts = [block.text for block in last.content if isinstance(block, TextContent)]
    return "\n".join(parts)


class ResearchOrchestrator:
    """两个科研角色 Agent 的确定性 v1 协调器。"""

    def __init__(
        self,
        *,
        coder: Agent,
        researcher: Agent,
        store: ProjectStore,
    ) -> None:
        self._agents: dict[Role, Agent] = {
            Role.CODER: coder,
            Role.RESEARCHER: researcher,
        }
        self._store = store

    def pick_agent(self, role: Role) -> Agent:
        return self._agents[role]

    def plan_next(self) -> Task | None:
        """确定性规划：取最旧的 pending 任务；首次调用时自动播种。"""
        state = self._store.project
        if not state.tasks:
            self._seed_initial_tasks(state)
        return state.next_pending_task()

    def _seed_initial_tasks(self, state: ProjectState) -> None:
        """启动新项目：文献调研 + baseline 检查。"""
        question = state.research_question
        state.tasks.append(
            Task(
                role=Role.RESEARCHER,
                title="Initial literature survey",
                prompt=(
                    f"Survey the literature for the research question: {question}. "
                    "List the papers you would collect and how they relate to the "
                    "baseline."
                ),
            )
        )
        state.tasks.append(
            Task(
                role=Role.CODER,
                title="Baseline inspection",
                prompt=(
                    "Inspect the uploaded baseline and propose a first validation "
                    "experiment. Describe what you would run and what results would "
                    "convince you."
                ),
            )
        )

    async def run(self, *, timeout: float | None = None) -> ProjectState:
        """运行协作，直到队列清空或达到迭代上限。"""
        store = self._store
        while True:
            state = store.project
            if state.iteration >= state.max_iterations:
                logger.info(
                    "Reached max iterations (%d); stopping.", state.max_iterations
                )
                break
            task = self.plan_next()
            if task is None:
                break
            await self._dispatch(task, timeout=timeout)
            state.iteration += 1
            store.commit()
        return store.snapshot()

    async def _dispatch(self, task: Task, *, timeout: float | None) -> None:
        """把单个任务交给对应角色 Agent 执行，并记录结果。"""
        state = self._store.project
        state.start_task(task)
        agent = self.pick_agent(task.role)
        logger.info("Dispatching task %s to %s", task.id, task.role.value)
        try:
            coro = agent.prompt(task.prompt)
            if timeout is not None:
                await asyncio.wait_for(coro, timeout=timeout)
            else:
                await coro
            text = _assistant_text(agent)
        except Exception as exc:  # 失败记录在任务上，循环继续运行
            logger.exception("Task %s failed", task.id)
            state.record_result(task, result="", error=str(exc))
            state.record_message(
                role=task.role, task_id=task.id, content=f"[error] {exc}"
            )
            return
        state.record_result(task, result=text)
        state.record_message(role=task.role, task_id=task.id, content=text)
