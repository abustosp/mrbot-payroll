"""Deterministic, offline provider used by tests and local dry runs."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from app.ai.errors import ProviderConfigurationError, ProviderError
from app.ai.schemas import LLMUsage


@dataclass(frozen=True, slots=True)
class MockCall:
    """One recorded invocation, useful to assert prompt hardening in tests."""

    system: str
    user: str


class MockProvider:
    """Return canned text without any network access.

    ``responses`` may be:

    * a single string, returned for every call;
    * a sequence of strings, consumed in order (an exhausted queue raises);
    * a callable receiving ``(system, user)`` and returning the response text.
    """

    def __init__(
        self,
        responses: str | Sequence[str] | Callable[[str, str], str] | None = None,
        *,
        usage: LLMUsage | Mapping[str, Any] | None = None,
        name: str = "mock",
    ) -> None:
        self.name = name
        self.last_usage: LLMUsage | None = None
        self.usage: LLMUsage | None = None
        self.calls: list[MockCall] = []
        self._fixed_usage = self._normalize_usage(usage)
        self._callable: Callable[[str, str], str] | None = None
        self._fixed_response: str | None = None
        self._queue: deque[str] = deque()

        if callable(responses):
            self._callable = responses
        elif isinstance(responses, str):
            self._fixed_response = responses
        elif responses is not None:
            if not isinstance(responses, Sequence):
                raise ProviderConfigurationError(
                    "MockProvider responses must be a string, a sequence or a callable"
                )
            self._queue = deque(responses)
        if self._callable is None and self._fixed_response is None and not self._queue:
            raise ProviderConfigurationError(
                "MockProvider needs a response, a sequence of responses or a callable"
            )

    @staticmethod
    def _normalize_usage(
        usage: LLMUsage | Mapping[str, Any] | None,
    ) -> LLMUsage | None:
        if usage is None or isinstance(usage, LLMUsage):
            return usage
        if isinstance(usage, Mapping):
            return LLMUsage.model_validate(dict(usage))
        raise ProviderConfigurationError("MockProvider usage must be an LLMUsage or mapping")

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def complete(self, system: str, user: str) -> str:
        self.calls.append(MockCall(system=system, user=user))
        self.last_usage = self._fixed_usage.model_copy(deep=True) if self._fixed_usage else None
        self.usage = self.last_usage

        if self._callable is not None:
            response = self._callable(system, user)
        elif self._fixed_response is not None:
            response = self._fixed_response
        elif self._queue:
            response = self._queue.popleft()
        else:
            raise ProviderError(
                "MockProvider response queue is exhausted; add another canned response"
            )

        if not isinstance(response, str):
            raise ProviderError("MockProvider callable must return a string")
        return response
