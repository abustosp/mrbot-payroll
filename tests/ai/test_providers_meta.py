"""Meta provider tests run offline via httpx.MockTransport."""

import json

import httpx
import pytest

from app.ai.errors import ProviderConfigurationError
from app.ai.providers.meta import MetaMuseProvider


def test_meta_defaults_and_request(monkeypatch):
    monkeypatch.setenv("PAYROLL_META_API_KEY", "meta-key")
    monkeypatch.delenv("PAYROLL_META_BASE_URL", raising=False)
    monkeypatch.delenv("PAYROLL_META_MODEL", raising=False)
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        provider = MetaMuseProvider(client=client)
        assert provider.complete("system", "user") == "{}"

    assert str(requests[0].url) == "https://api.meta.ai/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer meta-key"
    assert json.loads(requests[0].content)["model"] == "muse-spark-1.3-contributor"
    assert provider.name == "meta-muse"


def test_meta_documented_key_env(monkeypatch):
    for name in ("PAYROLL_META_API_KEY", "PAYROLL_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("MODEL_API_KEY", "documented-key")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        MetaMuseProvider(client=client).complete("system", "user")

    assert requests[0].headers["authorization"] == "Bearer documented-key"


def test_meta_environment_overrides_and_key_fallback(monkeypatch):
    monkeypatch.delenv("PAYROLL_META_API_KEY", raising=False)
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    monkeypatch.setenv("PAYROLL_AI_API_KEY", "fallback-key")
    monkeypatch.setenv("PAYROLL_META_BASE_URL", "https://example.test/compat/v1")
    monkeypatch.setenv("PAYROLL_META_MODEL", "custom-model")
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        MetaMuseProvider(client=client).complete("system", "user")

    assert str(requests[0].url) == "https://example.test/compat/v1/chat/completions"
    assert requests[0].headers["authorization"] == "Bearer fallback-key"
    assert json.loads(requests[0].content)["model"] == "custom-model"


def test_meta_missing_key(monkeypatch):
    for name in ("PAYROLL_META_API_KEY", "PAYROLL_AI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ProviderConfigurationError, match="API key"):
        MetaMuseProvider()
