"""HTTP client for OpenAI-compatible ``/chat/completions`` endpoints.

The provider is deliberately small and synchronous. Tests inject an
``httpx.Client`` backed by ``httpx.MockTransport``, so the suite never touches
the network.
"""

from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.ai.errors import (
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
)
from app.ai.schemas import LLMUsage

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_API_KEY_ENV = "PAYROLL_AI_API_KEY"


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return parsed if parsed.is_finite() else None


def _integer_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class OpenAICompatibleProvider:
    """Synchronous provider for OpenAI-compatible APIs.

    Configuration resolution order:

    * ``api_key`` argument, then ``$PAYROLL_AI_API_KEY`` (configurable env name),
      then ``$OPENAI_API_KEY``.
    * ``base_url`` argument, then ``$PAYROLL_AI_BASE_URL``, then the OpenAI URL.
    * ``model`` argument, then ``$PAYROLL_AI_MODEL``, then ``gpt-4o-mini``.

    An API key is mandatory and is never logged. The ``Authorization`` header is
    only attached to the injected ``httpx.Client`` request.
    """

    name = "openai-compatible"

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout: float = 30.0,
        api_key_env: str = DEFAULT_API_KEY_ENV,
        client: httpx.Client | None = None,
        temperature: float = 0.0,
        response_format_json: bool = True,
        prompt_cost_per_million: Decimal | float | str | None = None,
        completion_cost_per_million: Decimal | float | str | None = None,
    ) -> None:
        resolved_key = (
            api_key
            or os.environ.get(api_key_env)
            or os.environ.get("OPENAI_API_KEY")
        )
        if not resolved_key or not resolved_key.strip():
            raise ProviderConfigurationError(
                f"missing API key: set {api_key_env} (or OPENAI_API_KEY) in the environment"
            )
        self._api_key = resolved_key.strip()
        self.base_url = (
            base_url
            or os.environ.get("PAYROLL_AI_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or DEFAULT_BASE_URL
        ).rstrip("/")
        self.model = model or os.environ.get("PAYROLL_AI_MODEL") or DEFAULT_MODEL
        self.temperature = temperature
        self.response_format_json = response_format_json
        self.timeout = timeout
        self._owns_client = client is None
        self._client = client or httpx.Client(timeout=httpx.Timeout(timeout))
        self._prompt_cost_per_million = _decimal_or_none(prompt_cost_per_million)
        self._completion_cost_per_million = _decimal_or_none(completion_cost_per_million)
        self.last_usage: LLMUsage | None = None
        self.usage: LLMUsage | None = None

    @property
    def endpoint(self) -> str:
        return f"{self.base_url}/chat/completions"

    def complete(self, system: str, user: str) -> str:
        if not isinstance(system, str) or not isinstance(user, str):
            raise ProviderError("system and user prompts must be strings")

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": self.temperature,
        }
        if self.response_format_json:
            payload["response_format"] = {"type": "json_object"}

        try:
            response = self._client.post(
                self.endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
        except httpx.TimeoutException as exc:
            raise ProviderError(
                f"provider request timed out after {self.timeout} seconds"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderError(f"provider request failed: {exc}") from exc

        if response.status_code >= 400:
            detail = response.text[:500] if response.text else "no response body"
            raise ProviderError(
                f"provider returned HTTP {response.status_code}: {detail}"
            )

        try:
            data = response.json()
        except ValueError as exc:
            raise ProviderResponseError("provider returned a non-JSON HTTP body") from exc
        if not isinstance(data, dict):
            raise ProviderResponseError("provider returned an unexpected JSON payload")

        choices = data.get("choices")
        if not isinstance(choices, list) or not choices:
            raise ProviderResponseError("provider response has no choices")
        first = choices[0]
        message = first.get("message") if isinstance(first, dict) else None
        content = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content, str) or not content.strip():
            raise ProviderResponseError(
                "provider response has no assistant message content"
            )

        self.last_usage = self._build_usage(data.get("usage"))
        self.usage = self.last_usage
        return content

    def _build_usage(self, raw_usage: Any) -> LLMUsage | None:
        if not isinstance(raw_usage, dict):
            return None
        prompt_tokens = _integer_or_none(raw_usage.get("prompt_tokens"))
        completion_tokens = _integer_or_none(raw_usage.get("completion_tokens"))
        total_tokens = _integer_or_none(raw_usage.get("total_tokens"))
        if total_tokens is None and prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        cost = _decimal_or_none(raw_usage.get("cost"))
        if cost is None:
            cost = _decimal_or_none(raw_usage.get("cost_usd"))
        if cost is None:
            cost = _decimal_or_none(raw_usage.get("total_cost"))
        if cost is None and self._prompt_cost_per_million is not None:
            prompt_cost = (
                Decimal(prompt_tokens or 0) / Decimal(1_000_000)
            ) * self._prompt_cost_per_million
            completion_cost = (
                Decimal(completion_tokens or 0) / Decimal(1_000_000)
            ) * (self._completion_cost_per_million or Decimal("0"))
            cost = prompt_cost + completion_cost

        if (
            prompt_tokens is None
            and completion_tokens is None
            and total_tokens is None
            and cost is None
        ):
            return None
        return LLMUsage(
            provider=self.name,
            model=self.model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
        )

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> OpenAICompatibleProvider:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()
