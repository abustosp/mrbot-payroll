"""The provider contract consumed by the analysis pipeline."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMProvider(Protocol):
    """Minimal contract: a system prompt plus a user prompt yields text.

    Providers may additionally expose ``last_usage`` with an
    :class:`app.ai.schemas.LLMUsage` so the caller can record tokens and cost.
    Usage is optional because not every provider reports it.
    """

    def complete(self, system: str, user: str) -> str:  # pragma: no cover - protocol
        ...
