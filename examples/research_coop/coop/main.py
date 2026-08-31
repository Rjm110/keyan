"""科研协作骨架的演示入口。

运行一个确定性的双 Agent 项目（研究员 + 编码），目前没有真实工具，
也没有持久化。

运行方式：
    uv run python -m coop.main --question "..."
    uv run python -m coop.main --provider openai --question "..."

使用 ``--provider openai`` 可指向任意 OpenAI 兼容端点（例如 DeepSeek：
设置 DEEPSEEK_API_KEY）。默认使用 FauxProvider，因此无需 API key 即可演示。
"""

from __future__ import annotations

import argparse
import asyncio
import os

from cubepi.providers.base import BoundModel
from cubepi.providers.faux import FauxProvider, faux_assistant_message

from coop.orchestrator import ContextInjector, ResearchOrchestrator
from coop.roles import make_coder_agent, make_researcher_agent
from coop.state import ProjectStore
from coop.types import BaselineSpec, ProjectState

DEFAULT_QUESTION = (
    "Validate the uploaded baseline approach against the latest literature "
    "and propose one improvement."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行科研协作骨架。")
    parser.add_argument("--question", default=DEFAULT_QUESTION, help="研究问题。")
    parser.add_argument(
        "--provider",
        choices=("faux", "openai"),
        default="faux",
        help="faux = 确定性干跑；openai = OpenAI 兼容端点。",
    )
    parser.add_argument("--baseline-dir", default=None, help="可选的 baseline 路径。")
    parser.add_argument("--max-iterations", type=int, default=10)
    return parser.parse_args()


def _build_model(args: argparse.Namespace) -> BoundModel:
    if args.provider == "faux":
        provider = FauxProvider(provider_id="faux")
        provider.set_responses(
            [
                faux_assistant_message(
                    "Survey: three recent papers directly compare against this "
                    "baseline; details would come from search_papers once registered."
                ),
                faux_assistant_message(
                    "Baseline inspection: I would run a reproducibility script that "
                    "re-executes the baseline on the uploaded data and records "
                    "metrics per commit."
                ),
            ]
        )
        return provider.model("faux-model")

    api_key = os.environ.get("DEEPSEEK_API_KEY", os.environ.get("OPENAI_API_KEY", ""))
    base_url = os.environ.get("DEEPSEEK_BASE_URL") or os.environ.get("OPENAI_BASE_URL")
    model_id = os.environ.get("MODEL", "deepseek-chat")
    if not api_key:
        raise SystemExit(
            "Set DEEPSEEK_API_KEY (or OPENAI_API_KEY) to use --provider openai."
        )
    from cubepi.providers.openai import OpenAIProvider

    provider = OpenAIProvider(
        api_key=api_key,
        base_url=base_url,
        provider_id="openai",
    )
    return provider.model(model_id)


def _print_summary(state: ProjectState) -> None:
    print("\n=== 科研项目摘要 ===")
    print(f"项目：{state.name}")
    print(f"问题：{state.research_question}")
    print(f"已用迭代：{state.iteration}")
    print("任务：")
    for task in state.tasks:
        head = (task.result or task.error or "")[:80].replace("\n", " ")
        print(f"  - [{task.status.value}] {task.title}: {head}")
    print(f"已收集论文：{len(state.papers)}")
    print(f"已产出：{len(state.artifacts)}")
    print(f"已记录消息：{len(state.messages)}")


async def _main(args: argparse.Namespace) -> None:
    state = ProjectState(
        name="research-coop-demo",
        research_question=args.question,
        baseline=(
            BaselineSpec(name="baseline", source_path=args.baseline_dir)
            if args.baseline_dir
            else None
        ),
        max_iterations=args.max_iterations,
    )
    store = ProjectStore(state)
    model = _build_model(args)
    injector = ContextInjector(store)

    coder = make_coder_agent(model=model, middleware=[injector])
    researcher = make_researcher_agent(model=model, middleware=[injector])
    orchestrator = ResearchOrchestrator(coder=coder, researcher=researcher, store=store)

    final = await orchestrator.run()
    _print_summary(final)


if __name__ == "__main__":
    asyncio.run(_main(_parse_args()))
