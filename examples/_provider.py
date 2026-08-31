"""Shared provider setup for cubepi examples.

Set one of the following before running any example:

    # Anthropic (or Anthropic-compatible endpoint):
    export ANTHROPIC_API_KEY=sk-ant-...
    export ANTHROPIC_BASE_URL=https://...   # optional, for compatible endpoints
    export MODEL=claude-sonnet-4-6          # optional, this is the default

    # OpenAI (or OpenAI-compatible endpoint):
    export OPENAI_API_KEY=sk-...
    export OPENAI_BASE_URL=https://...      # optional, for compatible endpoints
    export MODEL=gpt-4o                     # optional, this is the default

    # OpenAI-compatible providers:
    export CUBEPI_PROVIDER=deepseek         # qwen, kimi, or glm also work
    export DEEPSEEK_API_KEY=sk-...           # use the matching provider key
    export MODEL=deepseek-chat               # optional

ANTHROPIC_API_KEY takes priority when both are set.
"""

import os
import sys

from cubepi.providers.presets import create_provider, get_provider_preset

_selected_provider = os.environ.get("CUBEPI_PROVIDER", "").strip().lower()
_anthropic_key = os.environ.get("ANTHROPIC_API_KEY")
_openai_key = os.environ.get("OPENAI_API_KEY")

if _selected_provider in {
    "deepseek",
    "qwen",
    "bailian",
    "dashscope",
    "kimi",
    "moonshot",
    "glm",
    "zhipu",
}:
    _preset = get_provider_preset(_selected_provider)
    provider = create_provider(_selected_provider)
    MODEL_ID = os.environ.get("MODEL", _preset.model)
elif _selected_provider and _selected_provider not in {"anthropic", "openai"}:
    print(
        "Error: CUBEPI_PROVIDER must be anthropic, openai, deepseek, qwen, kimi, or glm.",
        file=sys.stderr,
    )
    sys.exit(1)
elif _selected_provider == "anthropic" or _anthropic_key:
    from cubepi.providers.anthropic import AnthropicProvider

    _base_url = os.environ.get("ANTHROPIC_BASE_URL") or None
    provider = AnthropicProvider(api_key=_anthropic_key, base_url=_base_url)
    MODEL_ID = os.environ.get("MODEL", "claude-sonnet-4-6")
elif _selected_provider == "openai" or _openai_key:
    from cubepi.providers.openai import OpenAIProvider

    _base_url = os.environ.get("OPENAI_BASE_URL") or None
    provider = OpenAIProvider(api_key=_openai_key, base_url=_base_url)
    MODEL_ID = os.environ.get("MODEL", "gpt-4o")
else:
    print(
        "Error: set an API key or CUBEPI_PROVIDER before running examples.",
        file=sys.stderr,
    )
    sys.exit(1)
