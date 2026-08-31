# research_coop — multi-agent research skeleton

A minimal framework scaffold for a two-agent research collaboration built on
CubePi:

- **researcher** — searches and organizes papers (`Role.RESEARCHER`)
- **coder** — validates an uploaded baseline by writing/running experiments
  (`Role.CODER`)

This is intentionally a **skeleton**: no tools are registered and nothing is
persisted yet. The seams for both are in place and documented below.

## Layout

```text
research_coop/
├── coop/
│   ├── types.py          # ProjectState / Task / PaperRef / Artifact / ... (pure pydantic)
│   ├── roles.py          # role prompts + tool-slot declarations + agent factories
│   ├── state.py          # ProjectStore + ProjectStorage protocol (persistence seam)
│   ├── orchestrator.py   # ContextInjector middleware + deterministic ResearchOrchestrator
│   └── main.py           # demo entry point
└── tests/                # pytest suite (run explicitly, excluded from repo testpaths)
```

## Run

```bash
# Dry run with the deterministic FauxProvider (no API key needed)
uv run python -m coop.main --question "Does the baseline reproduce?"

# Against any OpenAI-compatible endpoint (e.g. DeepSeek)
$env:DEEPSEEK_API_KEY = "sk-..."     # or OPENAI_API_KEY
uv run python -m coop.main --provider openai --question "..."
```

To import `coop` from the repo root instead of the example directory, it is
simpler to `cd examples/research_coop` first (the demo above assumes that).

## Tests

```bash
uv run pytest examples/research_coop/tests
```

## Extension seams (next steps)

- **Tools** — `roles.TOOL_SLOTS` declares what each role will eventually do
  (`run_experiment`, `search_papers`, ...). Register real
  `cubepi.agent.types.AgentTool`s by passing `tools=[...]` to
  `make_role_agent`; prompts already describe them.
- **Persistence** — implement `coop.state.ProjectStorage` (JSONL or
  `SqliteCheckpointer`) and pass it to `ProjectStore`; the orchestrator
  already calls `store.commit()` after every task.
- **Smarter planning** — `ResearchOrchestrator.plan_next()` is the single
  pluggable decision point; swap in an LLM planner later without touching
  dispatch or state.
- **Real providers** — the demo reads `DEEPSEEK_API_KEY` /
  `OPENAI_API_KEY`; per-vendor `CapabilityDescriptor` presets can be added
  when more vendors are needed.

## Design notes

- The orchestrator is a plain async while-loop (plan -> dispatch -> collect
  -> decide), mirroring CubePi's own agent loop; no graph runtime.
- Role agents are stateless CubePi `Agent`s. Shared project context is injected
  by `ContextInjector` via `transform_system_prompt`, so every model call sees
  the live queue / papers / artifacts / iteration.
- Task failures are recorded per task (`TaskStatus.FAILED`) and the loop
  continues; `max_iterations` is the hard stop.
