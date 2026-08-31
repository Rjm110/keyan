from __future__ import annotations

from typing import Any

from cubepi.providers.capability import CapabilityDescriptor
from cubepi.providers.openai import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    """Provider for services exposing an OpenAI Chat Completions endpoint.

    The implementation intentionally reuses :class:`OpenAIProvider`. Vendor
    differences belong in ``CapabilityDescriptor`` and request options rather
    than in duplicated streaming implementations.
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        extra_body: dict[str, Any] | None = None,
        extra_headers: dict[str, str] | None = None,
        include_usage: bool = True,
        capability: CapabilityDescriptor | None = None,
        model_capability_overrides: dict[str, CapabilityDescriptor] | None = None,
        provider_id: str = "",
    ) -> None:
        super().__init__(
            api_key=api_key,
            base_url=base_url,
            extra_body=extra_body,
            extra_headers=extra_headers,
            include_usage=include_usage,
            capability=capability,
            model_capability_overrides=model_capability_overrides,
            provider_id=provider_id,
        )
