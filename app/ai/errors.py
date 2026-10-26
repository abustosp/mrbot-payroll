"""Errors raised by the supervised AI pipeline.

The messages are intentionally explicit: this package feeds a regulated payroll
workflow, so every failure has to be actionable by a human reviewer.
"""

from __future__ import annotations


class AIError(Exception):
    """Base class for every error raised by :mod:`app.ai`."""


class DocumentExtractionError(AIError, ValueError):
    """The document could not be converted to text."""


class UnsupportedDocumentError(DocumentExtractionError):
    """The file extension is not supported by the extractor."""


class DocumentTooLargeError(AIError, ValueError):
    """The document exceeds the configured analysis limit."""


class ProviderError(AIError):
    """The language model provider failed."""


class ProviderConfigurationError(ProviderError, ValueError):
    """The provider is missing configuration such as an API key."""


class ProviderResponseError(ProviderError):
    """The provider returned an unusable response."""


class AnalysisError(AIError, ValueError):
    """The model response could not be turned into a valid analysis."""


class ProposalError(AIError, ValueError):
    """A proposal could not be created or transitioned."""


class ApprovalError(ProposalError):
    """An approval was requested without the required human data."""
