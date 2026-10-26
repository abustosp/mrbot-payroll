"""Provider tests run fully offline via httpx.MockTransport."""

from __future__ import annotations

import json
from decimal import Decimal

import httpx
import pytest

from app.ai.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
)
from app.ai.providers import MockProvider, OpenAICompatibleProvider
from app.ai.schemas import LLMUsage


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


def _success_response(content: str = '{"ok": true}') -> dict:
    return {
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
        },
    }


def test_mock_provider_returns_fixed_response_and_records_calls():
    usage = LLMUsage(prompt_tokens=3, completion_tokens=4, total_tokens=7)
    provider = MockProvider('{"x": 1}', usage=usage)
    assert provider.complete("system", "user") == '{"x": 1}'
    assert provider.complete("system2", "user2") == '{"x": 1}'
    assert provider.call_count == 2
    assert provider.calls[0].system == "system"
    assert provider.last_usage == usage


def test_mock_provider_accepts_usage_mapping_and_exposes_alias():
    provider = MockProvider(
        "{}", usage={"prompt_tokens": 2, "completion_tokens": 3}
    )
    provider.complete("s", "u")
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_tokens == 2
    assert provider.usage == provider.last_usage


def test_mock_provider_queue_is_consumed_then_fails():
    provider = MockProvider(["one", "two"])
    assert provider.complete("s", "u") == "one"
    assert provider.complete("s", "u") == "two"
    with pytest.raises(ProviderError, match="exhausted"):
        provider.complete("s", "u")


def test_mock_provider_callable_receives_prompts():
    seen = {}

    def responder(system: str, user: str) -> str:
        seen["system"] = system
        seen["user"] = user
        return "{}"

    provider = MockProvider(responder)
    assert provider.complete("sys", "usr") == "{}"
    assert seen == {"system": "sys", "user": "usr"}


def test_openai_compatible_success_and_usage():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=_success_response())

    client = _client(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        model="test-model",
        client=client,
    )
    assert provider.complete("system", "user") == '{"ok": true}'
    request = requests[0]
    assert str(request.url) == "https://example.test/v1/chat/completions"
    assert request.headers["authorization"] == "Bearer test-key"
    body = json.loads(request.content)
    assert body["messages"][0] == {"role": "system", "content": "system"}
    assert body["messages"][1] == {"role": "user", "content": "user"}
    assert body["response_format"] == {"type": "json_object"}
    assert provider.last_usage is not None
    assert provider.last_usage.prompt_tokens == 10
    assert provider.last_usage.completion_tokens == 5
    assert provider.last_usage.total_tokens == 15
    assert provider.last_usage.provider == "openai-compatible"
    assert provider.last_usage.cost_usd is None
    client.close()


def test_openai_compatible_computes_cost_when_pricing_is_configured():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_success_response())

    client = _client(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
        prompt_cost_per_million="1",
        completion_cost_per_million="2",
    )
    payload = _success_response()
    payload["usage"] = {
        "prompt_tokens": 1_000_000,
        "completion_tokens": 500_000,
        "total_tokens": 1_500_000,
    }

    client.close()
    client = _client(lambda request: httpx.Response(200, json=payload))
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
        prompt_cost_per_million="1",
        completion_cost_per_million="2",
    )
    provider.complete("s", "u")
    assert provider.last_usage is not None
    assert provider.last_usage.cost_usd == Decimal("2.0")
    client.close()


def test_api_key_is_read_from_environment(monkeypatch):
    monkeypatch.setenv("PAYROLL_AI_API_KEY", "env-key")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["authorization"])
        return httpx.Response(200, json=_success_response())

    client = _client(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        client=client,
    )
    provider.complete("s", "u")
    assert seen == ["Bearer env-key"]
    client.close()


def test_missing_api_key_fails_clearly(monkeypatch):
    monkeypatch.delenv("PAYROLL_AI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderConfigurationError, match="API key"):
        OpenAICompatibleProvider(base_url="https://example.test/v1")


def test_http_error_is_wrapped():
    client = _client(lambda request: httpx.Response(401, text="bad key"))
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
    )
    with pytest.raises(ProviderError, match="HTTP 401"):
        provider.complete("s", "u")
    client.close()


def test_malformed_json_body_is_wrapped():
    client = _client(lambda request: httpx.Response(200, text="<html>oops</html>"))
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
    )
    with pytest.raises(ProviderResponseError, match="non-JSON"):
        provider.complete("s", "u")
    client.close()


def test_missing_choice_content_is_wrapped():
    client = _client(
        lambda request: httpx.Response(200, json={"choices": [{"message": {}}]})
    )
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
    )
    with pytest.raises(ProviderResponseError, match="content"):
        provider.complete("s", "u")
    client.close()


def test_timeout_is_wrapped():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    client = _client(handler)
    provider = OpenAICompatibleProvider(
        base_url="https://example.test/v1",
        api_key="test-key",
        client=client,
    )
    with pytest.raises(ProviderError, match="timed out"):
        provider.complete("s", "u")
    client.close()
