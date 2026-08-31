from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from unittest.mock import patch

import pytest

from cubepi.providers.openai_compatible import OpenAICompatibleProvider
from cubepi.providers.presets import create_provider, get_provider_preset


class TestProviderPresets:
    def test_supported_presets_have_distinct_endpoints(self):
        names = ("deepseek", "qwen", "kimi", "glm")
        presets = [get_provider_preset(name) for name in names]

        assert [preset.provider_id for preset in presets] == list(names)
        assert len({preset.base_url for preset in presets}) == len(names)

    def test_aliases_resolve_to_canonical_presets(self):
        assert get_provider_preset("bailian") is get_provider_preset("qwen")
        assert get_provider_preset("moonshot") is get_provider_preset("kimi")
        assert get_provider_preset("zhipu") is get_provider_preset("glm")

    def test_environment_values_and_explicit_values(self, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "env-key")
        monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://proxy.example/v1")

        with patch("openai.AsyncOpenAI") as sdk:
            provider = create_provider(
                "deepseek",
                api_key="explicit-key",
                base_url="https://explicit.example/v1",
            )

        assert isinstance(provider, OpenAICompatibleProvider)
        assert provider.provider_id == "deepseek"
        sdk.assert_called_once_with(
            api_key="explicit-key",
            base_url="https://explicit.example/v1",
        )

    def test_preset_key_and_url_are_read_from_environment(self, monkeypatch):
        monkeypatch.setenv("ZHIPUAI_API_KEY", "glm-key")

        with patch("openai.AsyncOpenAI") as sdk:
            provider = create_provider("glm")

        assert provider.provider_id == "glm"
        sdk.assert_called_once_with(
            api_key="glm-key",
            base_url="https://open.bigmodel.cn/api/paas/v4",
        )

    def test_unknown_preset_lists_supported_names(self):
        try:
            get_provider_preset("unknown")
        except ValueError as exc:
            assert "deepseek" in str(exc)
            assert "qwen" in str(exc)
        else:  # pragma: no cover
            raise AssertionError("unknown provider preset should fail")

    @pytest.mark.asyncio
    async def test_can_omit_stream_usage_for_strict_compatibles(self):
        async def stream_chunks():
            yield SimpleNamespace(
                id="chatcmpl-1",
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content="ok", tool_calls=None),
                        finish_reason=None,
                    )
                ],
            )
            yield SimpleNamespace(
                id=None,
                choices=[
                    SimpleNamespace(
                        delta=SimpleNamespace(content=None, tool_calls=None),
                        finish_reason="stop",
                    )
                ],
            )

        client = MagicMock()
        client.chat.completions.create = AsyncMock(return_value=stream_chunks())
        provider = OpenAICompatibleProvider(
            api_key="test-key",
            base_url="https://example.test/v1",
            include_usage=False,
        )
        provider._client = client

        stream = await provider.stream(
            provider.model("example-model").spec,
            [],
        )
        await stream.result()

        payload = client.chat.completions.create.call_args.kwargs
        assert "stream_options" not in payload
