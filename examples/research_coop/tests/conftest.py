"""research_coop 骨架测试的共享夹具。

让 ``coop`` 包可被导入，并提供一个基于 FauxProvider 的模型和
一个已播种任务的 ProjectStore。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cubepi.providers.faux import (  # noqa: E402
    FauxProvider,
    faux_assistant_message,
)

from coop.state import ProjectStore  # noqa: E402
from coop.types import ProjectState, Role, Task  # noqa: E402


@pytest.fixture
def faux_provider() -> FauxProvider:
    provider = FauxProvider(provider_id="faux")
    provider.set_responses([faux_assistant_message("default answer")])
    return provider


@pytest.fixture
def faux_model(faux_provider: FauxProvider):
    return faux_provider.model("faux-model")


@pytest.fixture
def seeded_store() -> ProjectStore:
    """一个已排队研究员与编码任务各一的项目。"""
    state = ProjectState(
        name="test-project",
        research_question="Does the baseline reproduce?",
        tasks=[
            Task(
                role=Role.RESEARCHER,
                title="survey",
                prompt="survey the literature",
            ),
            Task(role=Role.CODER, title="reproduce", prompt="reproduce the baseline"),
        ],
        max_iterations=4,
    )
    return ProjectStore(state)
