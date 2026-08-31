"""确定性科研编排器的测试。"""

from __future__ import annotations

from cubepi.providers.faux import faux_assistant_message

from coop.orchestrator import ContextInjector, ResearchOrchestrator
from coop.roles import make_coder_agent, make_researcher_agent
from coop.types import Role, TaskStatus


def _build_orchestrator(*, faux_model, faux_provider, store):
    faux_provider.set_responses(
        [
            faux_assistant_message("survey result"),
            faux_assistant_message("baseline result"),
        ]
    )
    injector = ContextInjector(store)
    coder = make_coder_agent(model=faux_model, middleware=[injector])
    researcher = make_researcher_agent(model=faux_model, middleware=[injector])
    return ResearchOrchestrator(coder=coder, researcher=researcher, store=store)


class TestOrchestratorLoop:
    async def test_runs_all_queued_tasks(self, faux_model, faux_provider, seeded_store):
        orch = _build_orchestrator(
            faux_model=faux_model, faux_provider=faux_provider, store=seeded_store
        )

        final = await orch.run()

        assert final.iteration == 2
        assert all(t.status == TaskStatus.DONE for t in final.tasks)
        assert [t.result for t in final.tasks] == ["survey result", "baseline result"]
        assert len(final.messages) == 2

    async def test_researcher_task_runs_first(
        self, faux_model, faux_provider, seeded_store
    ):
        orch = _build_orchestrator(
            faux_model=faux_model, faux_provider=faux_provider, store=seeded_store
        )

        await orch.run()

        assert seeded_store.project.tasks[0].role == Role.RESEARCHER
        assert seeded_store.project.tasks[0].result == "survey result"

    async def test_seeds_initial_tasks_when_queue_empty(
        self, faux_model, faux_provider, seeded_store
    ):
        seeded_store.project.tasks = []
        faux_provider.set_responses(
            [
                faux_assistant_message("survey result"),
                faux_assistant_message("baseline result"),
            ]
        )
        orch = _build_orchestrator(
            faux_model=faux_model, faux_provider=faux_provider, store=seeded_store
        )

        final = await orch.run()

        assert len(final.tasks) == 2
        assert final.tasks[0].role == Role.RESEARCHER  # 调研任务先播种

    async def test_max_iterations_stops_loop(
        self, faux_model, faux_provider, seeded_store
    ):
        seeded_store.project.max_iterations = 1
        faux_provider.set_responses(
            [
                faux_assistant_message("survey result"),
                faux_assistant_message("baseline result"),
            ]
        )
        orch = _build_orchestrator(
            faux_model=faux_model, faux_provider=faux_provider, store=seeded_store
        )

        final = await orch.run()

        assert final.iteration == 1
        assert final.tasks[0].status == TaskStatus.DONE
        assert final.tasks[1].status == TaskStatus.PENDING

    async def test_failed_task_is_recorded_and_loop_continues(
        self, faux_model, faux_provider, seeded_store
    ):
        async def explode(message, **kwargs):
            raise RuntimeError("provider down")

        injector = ContextInjector(seeded_store)
        coder = make_coder_agent(model=faux_model, middleware=[injector])
        researcher = make_researcher_agent(model=faux_model, middleware=[injector])
        researcher.prompt = explode  # type: ignore[method-assign]
        faux_provider.set_responses([faux_assistant_message("baseline result")])

        orch = ResearchOrchestrator(
            coder=coder, researcher=researcher, store=seeded_store
        )

        final = await orch.run()

        assert final.tasks[0].status == TaskStatus.FAILED
        assert "provider down" in (final.tasks[0].error or "")
        assert final.tasks[1].status == TaskStatus.DONE
        assert final.tasks[1].result == "baseline result"
        assert len(final.messages) == 2


class TestContextInjector:
    async def test_injects_project_snapshot_into_system_prompt(
        self, faux_model, faux_provider, seeded_store
    ):
        injector = ContextInjector(seeded_store)
        coder = make_coder_agent(model=faux_model, middleware=[injector])

        await coder.prompt("run the experiment")

        cached = faux_provider.prompt_cache["default"]
        assert "test-project" in cached
        assert "Does the baseline reproduce?" in cached
        assert "Shared project state" in cached
