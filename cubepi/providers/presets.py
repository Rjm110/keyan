from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from cubepi.providers.capability import CapabilityDescriptor
from cubepi.providers.openai_compatible import OpenAICompatibleProvider


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    provider_id: str
    api_key_env: str
    base_url_env: str
    base_url: str
    model: str
    capability: CapabilityDescriptor
    include_usage: bool = True


_PRESETS: dict[str, ProviderPreset] = {
    "deepseek": ProviderPreset(
        name="DeepSeek",
        provider_id="deepseek",
        api_key_env="DEEPSEEK_API_KEY",
        base_url_env="DEEPSEEK_BASE_URL",
        base_url="https://api.deepseek.com",
        model="deepseek-v4-flash",
        capability=CapabilityDescriptor(supports_tools=True),
    ),
    "qwen": ProviderPreset(
        name="Qwen / Bailian",
        provider_id="qwen",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        model="qwen-plus",
        capability=CapabilityDescriptor(supports_tools=True),
    ),
    "kimi": ProviderPreset(
        name="Kimi",
        provider_id="kimi",
        api_key_env="MOONSHOT_API_KEY",
        base_url_env="MOONSHOT_BASE_URL",
        base_url="https://api.moonshot.cn/v1",
        model="moonshot-v1-8k",
        capability=CapabilityDescriptor(supports_tools=True),
    ),
    "glm": ProviderPreset(
        name="GLM",
        provider_id="glm",
        api_key_env="ZHIPUAI_API_KEY",
        base_url_env="ZHIPUAI_BASE_URL",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4-flash",
        capability=CapabilityDescriptor(supports_tools=True),
    ),
    "opencode": ProviderPreset(
        name="OpenCode Go",
        provider_id="opencode",
        api_key_env="OPENCODE_API_KEY",
        base_url_env="OPENCODE_BASE_URL",
        base_url="https://opencode.ai/zen/go/v1",
        model="deepseek-v4-flash",
        capability=CapabilityDescriptor(supports_tools=True),
    ),
}

_ALIASES = {
    "bailian": "qwen",
    "dashscope": "qwen",
    "moonshot": "kimi",
    "zhipu": "glm",
}


def get_provider_preset(name: str) -> ProviderPreset:
    """Return a built-in preset for an OpenAI-compatible provider."""
    key = name.strip().lower()
    key = _ALIASES.get(key, key)
    try:
        return _PRESETS[key]
    except KeyError as exc:
        supported = ", ".join(sorted(_PRESETS))
        raise ValueError(
            f"Unknown provider preset {name!r}; choose: {supported}"
        ) from exc


def create_provider(
    name: str,
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    extra_body: dict[str, Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    include_usage: bool | None = None,
    capability: CapabilityDescriptor | None = None,
    provider_id: str | None = None,
) -> OpenAICompatibleProvider:
    """Create a configured OpenAI-compatible provider from a built-in preset.

    Explicit arguments take precedence over environment variables and preset
    defaults. API keys are read lazily so importing this module is side-effect
    free.
    """
    preset = get_provider_preset(name)
    resolved_key = (
        api_key if api_key is not None else os.environ.get(preset.api_key_env)
    )
    resolved_url = (
        base_url
        if base_url is not None
        else os.environ.get(preset.base_url_env, preset.base_url)
    )
    return OpenAICompatibleProvider(
        api_key=resolved_key,
        base_url=resolved_url,
        extra_body=extra_body,
        extra_headers=extra_headers,
        include_usage=(
            preset.include_usage if include_usage is None else include_usage
        ),
        capability=capability or preset.capability,
        provider_id=provider_id or preset.provider_id,
    )


def available_provider_presets() -> tuple[str, ...]:
    """Return the canonical names of the built-in compatible presets."""
    return tuple(sorted(_PRESETS))
