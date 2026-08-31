"""coop.types 纯数据模型的测试。"""

from __future__ import annotations

from coop.state import ProjectStore
from coop.types import (
    AgentMessage,
    Artifact,
    PaperRef,
    ProjectState,
    Role,
    Task,
    TaskStatus,
)


class TestTaskQueue:
    def test_next_pending_task_returns_oldest_pending(self):
        state = ProjectState(name="p", research_question="q")
        first = Task(role=Role.RESEARCHER, title="a", prompt="p1")
        second = Task(role=Role.CODER, title="b", prompt="p2")
        state.tasks = [first, second]

        assert state.next_pending_task() is first

    def test_done_tasks_are_skipped(self):
        state = ProjectState(name="p", research_question="q")
        done = Task(
            role=Role.RESEARCHER, title="a", prompt="p1", status=TaskStatus.DONE
        )
        pending = Task(role=Role.CODER, title="b", prompt="p2")
        state.tasks = [done, pending]

        assert state.next_pending_task() is pending

    def test_empty_queue_returns_none(self):
        state = ProjectState(name="p", research_question="q")
        assert state.next_pending_task() is None


class TestResultRecording:
    def test_record_result_marks_done_and_stores_text(self):
        task = Task(role=Role.CODER, title="t", prompt="p")
        state = ProjectState(name="p", research_question="q", tasks=[task])

        state.start_task(task)
        state.record_result(task, "all green")

        assert task.status == TaskStatus.DONE
        assert task.result == "all green"
        assert task.error is None

    def test_record_result_with_error_marks_failed(self):
        task = Task(role=Role.CODER, title="t", prompt="p")
        state = ProjectState(name="p", research_question="q", tasks=[task])

        state.record_result(task, "", error="boom")

        assert task.status == TaskStatus.FAILED
        assert task.error == "boom"

    def test_record_message_appends_in_order(self):
        state = ProjectState(name="p", research_question="q")
        state.record_message(role=Role.RESEARCHER, task_id="t1", content="paper list")
        state.record_message(role=Role.CODER, task_id="t2", content="experiment notes")

        assert len(state.messages) == 2
        assert [m.role for m in state.messages] == [Role.RESEARCHER, Role.CODER]
        assert all(isinstance(m, AgentMessage) for m in state.messages)


class TestCollections:
    def test_add_paper_and_artifact(self):
        state = ProjectState(name="p", research_question="q")
        state.add_paper(PaperRef(title="A paper"))
        state.add_artifact(
            Artifact(name="run.py", kind="code", path="artifacts/run.py")
        )

        assert len(state.papers) == 1
        assert len(state.artifacts) == 1

    def test_context_snapshot_includes_question_and_counts(self):
        state = ProjectState(
            name="p",
            research_question="does it work?",
            tasks=[Task(role=Role.RESEARCHER, title="t", prompt="p")],
        )
        state.add_paper(PaperRef(title="A paper"))

        snapshot = state.context_snapshot()

        assert "does it work?" in snapshot
        assert "[pending] t (researcher)" in snapshot
        assert "Papers collected: 1" in snapshot


class TestStoreIsolation:
    def test_snapshot_is_a_deep_copy(self):
        state = ProjectState(
            name="p",
            research_question="q",
            tasks=[Task(role=Role.CODER, title="t", prompt="p")],
        )
        store = ProjectStore(state)

        snap = store.snapshot()
        snap.tasks[0].result = "mutated"

        assert store.project.tasks[0].result is None
        assert snap.tasks[0].result == "mutated"
