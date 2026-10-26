"""Supervised agreement analysis.

The model only fills a structured proposal. This module owns identity, hashes,
review state and untrusted-content handling, so an LLM cannot fabricate
traceability or pre-approve a rule.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, NoReturn

from pydantic import ValidationError

from app.ai.errors import AnalysisError, DocumentTooLargeError, ProviderResponseError
from app.ai.hashing import compute_content_hash
from app.ai.prompts import prompt_pair
from app.ai.providers.base import LLMProvider
from app.ai.schemas import (
    AgreementAnalysis,
    DocumentMetadata,
    LLMUsage,
    ProposalStatus,
    ProposedConcept,
    ProposedFormula,
    ProposedParameter,
    SourceReference,
)
from app.ai.security import detect_prompt_injection

DEFAULT_MAX_CHARS = 400_000
_FENCE_RE = re.compile(
    r"\A```(?:json)?[ \t]*\r?\n?(.*?)\r?\n?```[ \t]*\Z",
    re.DOTALL | re.IGNORECASE,
)


def analyze_agreement(
    text: str,
    provider: LLMProvider,
    metadata: DocumentMetadata | Mapping[str, Any],
    *,
    max_chars: int = DEFAULT_MAX_CHARS,
    now: datetime | None = None,
) -> AgreementAnalysis:
    """Analyze agreement text and return a draft-only structured proposal.

    The document is sent as untrusted data. The response must be a single JSON
    object (optionally inside a Markdown fence); every source is rebound to the
    real document hash and every formula is forced to ``draft``.
    """

    if not isinstance(text, str):
        raise AnalysisError("agreement text must be a string")
    normalized_text = text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized_text.strip():
        raise AnalysisError("agreement text is empty")
    if max_chars <= 0:
        raise AnalysisError("max_chars must be positive")
    if len(normalized_text) > max_chars:
        raise DocumentTooLargeError(
            f"document has {len(normalized_text)} characters; the configured limit "
            f"is {max_chars}. Split the agreement or raise the limit explicitly."
        )
    if not callable(getattr(provider, "complete", None)):
        raise AnalysisError(
            "provider must implement complete(system, user) -> str as LLMProvider"
        )

    document_metadata = _coerce_metadata(metadata)
    computed_hash = compute_content_hash(normalized_text)
    if (
        document_metadata.content_hash is not None
        and document_metadata.content_hash != computed_hash
    ):
        raise AnalysisError(
            "metadata content_hash does not match the supplied text; refusing to "
            "analyze a document whose integrity cannot be confirmed"
        )
    document_metadata = DocumentMetadata.model_validate(
        {
            **document_metadata.model_dump(mode="python"),
            "content_hash": computed_hash,
        }
    )

    injection_warnings = detect_prompt_injection(normalized_text)
    system_prompt, user_prompt = prompt_pair(normalized_text, document_metadata)

    raw_response = provider.complete(system_prompt, user_prompt)
    if not isinstance(raw_response, str):
        raise ProviderResponseError(
            "provider.complete() must return text, got "
            f"{type(raw_response).__name__}"
        )

    payload = _parse_json_object(raw_response)
    timestamp = now or datetime.now(UTC)
    usage = _provider_usage(provider)

    # System-owned fields always win over anything the model produced.
    payload["analysis_version"] = "1.0"
    payload["document"] = document_metadata.model_dump(mode="json")
    payload["analyzed_at"] = timestamp.isoformat()
    payload["untrusted_content"] = True
    payload["provider_usage"] = (
        usage.model_dump(mode="json") if usage is not None else None
    )
    payload["security_warnings"] = list(injection_warnings)

    try:
        analysis = AgreementAnalysis.model_validate(payload)
    except ValidationError as exc:
        raise AnalysisError(_format_validation_error(exc)) from exc

    return _bind_and_sanitize(analysis, document_metadata, injection_warnings)


def _coerce_metadata(
    metadata: DocumentMetadata | Mapping[str, Any],
) -> DocumentMetadata:
    if isinstance(metadata, DocumentMetadata):
        return metadata
    if isinstance(metadata, Mapping):
        try:
            return DocumentMetadata.model_validate(dict(metadata))
        except ValidationError as exc:
            raise AnalysisError(
                "invalid document metadata: " + _format_validation_error(exc)
            ) from exc
    raise AnalysisError("metadata must be DocumentMetadata or a mapping")


def _parse_json_object(raw_response: str) -> dict[str, Any]:
    if not isinstance(raw_response, str) or not raw_response.strip():
        raise AnalysisError("provider returned an empty response")
    payload_text = _strip_markdown_fence(raw_response.strip().lstrip("\ufeff"))
    try:
        parsed = json.loads(
            payload_text,
            object_pairs_hook=_object_without_duplicate_keys,
            parse_constant=_reject_non_finite_json,
        )
    except _DuplicateKeyError as exc:
        raise AnalysisError(f"Invalid analysis JSON: duplicate key {exc.key!r}") from exc
    except json.JSONDecodeError as exc:
        raise AnalysisError(
            f"Invalid analysis JSON at line {exc.lineno}, column {exc.colno}: "
            f"{exc.msg}"
        ) from exc
    except ValueError as exc:
        raise AnalysisError(f"Invalid analysis JSON: {exc}") from exc

    if not isinstance(parsed, dict):
        raise AnalysisError(
            f"analysis JSON must be an object, got {type(parsed).__name__}"
        )
    return parsed


def _strip_markdown_fence(value: str) -> str:
    if not value.startswith("```"):
        return value
    match = _FENCE_RE.match(value)
    if match is None:
        raise AnalysisError(
            "Invalid analysis JSON: malformed or unterminated Markdown code fence"
        )
    return match.group(1).strip()


class _DuplicateKeyError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(f"duplicate key {key!r}")
        self.key = key


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise _DuplicateKeyError(key)
        result[key] = value
    return result


def _reject_non_finite_json(value: str) -> NoReturn:
    raise ValueError(f"non-finite number {value!r} is not allowed")


def _format_validation_error(exc: ValidationError) -> str:
    parts: list[str] = []
    for error in exc.errors(include_url=False, include_input=False)[:10]:
        location = ".".join(str(item) for item in error["loc"]) or "<root>"
        parts.append(f"{location}: {error['msg']}")
    suffix = "" if len(exc.errors()) <= 10 else f" (+{len(exc.errors()) - 10} more)"
    return "Invalid analysis schema: " + "; ".join(parts) + suffix


def _provider_usage(provider: LLMProvider) -> LLMUsage | None:
    usage = getattr(provider, "last_usage", None)
    if usage is None:
        usage = getattr(provider, "usage", None)
    if usage is None:
        return None
    if isinstance(usage, LLMUsage):
        model = usage
    elif isinstance(usage, Mapping):
        try:
            model = LLMUsage.model_validate(dict(usage))
        except ValidationError:
            return None
    else:
        return None

    updates: dict[str, Any] = {}
    if model.provider is None:
        provider_name = getattr(provider, "name", None)
        if isinstance(provider_name, str) and provider_name:
            updates["provider"] = provider_name
    if model.model is None:
        model_name = getattr(provider, "model", None)
        if isinstance(model_name, str) and model_name:
            updates["model"] = model_name
    if (
        model.total_tokens is None
        and model.prompt_tokens is not None
        and model.completion_tokens is not None
    ):
        updates["total_tokens"] = model.prompt_tokens + model.completion_tokens
    return model.model_copy(update=updates) if updates else model


def _bind_and_sanitize(
    analysis: AgreementAnalysis,
    metadata: DocumentMetadata,
    security_warnings: list[str],
) -> AgreementAnalysis:
    warnings = list(security_warnings)
    supplied_hashes = 0

    concepts: list[ProposedConcept] = []
    for concept in analysis.concepts:
        bound, had_hash = _bind_source(concept.source, metadata)
        supplied_hashes += int(had_hash)
        concepts.append(concept.model_copy(update={"source": bound}))

    parameters: list[ProposedParameter] = []
    for parameter in analysis.parameters:
        bound, had_hash = _bind_source(parameter.source, metadata)
        supplied_hashes += int(had_hash)
        parameters.append(parameter.model_copy(update={"source": bound}))

    formulas: list[ProposedFormula] = []
    for formula in analysis.formulas:
        bound, had_hash = _bind_source(formula.source, metadata)
        supplied_hashes += int(had_hash)
        if (
            formula.status is not ProposalStatus.DRAFT
            or formula.approved_by is not None
            or formula.approved_at is not None
            or formula.rejected_by is not None
            or formula.rejection_reason is not None
            or formula.validation is not None
        ):
            warnings.append(
                f"Model output tried to set review state on formula {formula.code!r}; "
                "it was forcibly reset to draft with no approval or validation data."
            )
        formulas.append(
            formula.model_copy(
                update={
                    "source": bound,
                    "status": ProposalStatus.DRAFT,
                    "approved_by": None,
                    "approved_at": None,
                    "rejected_by": None,
                    "rejected_at": None,
                    "rejection_reason": None,
                    "validation": None,
                }
            )
        )

    if supplied_hashes:
        warnings.append(
            "The model supplied content_hash values; they were ignored and replaced "
            "with the hash computed from the analyzed document."
        )

    return analysis.model_copy(
        update={
            "document": metadata,
            "concepts": concepts,
            "parameters": parameters,
            "formulas": formulas,
            "security_warnings": warnings,
            "untrusted_content": True,
        }
    )


def _bind_source(
    source: SourceReference, metadata: DocumentMetadata
) -> tuple[SourceReference, bool]:
    if source.document_id != metadata.document_id:
        raise AnalysisError(
            f"source cites document_id {source.document_id!r} but the analyzed "
            f"document is {metadata.document_id!r}; fabricated or mismatched "
            "sources are not accepted"
        )
    if source.version != metadata.version:
        raise AnalysisError(
            f"source cites version {source.version!r} but the analyzed version is "
            f"{metadata.version!r}; a proposal must cite the analyzed document"
        )
    return (
        source.model_copy(update={"content_hash": metadata.content_hash}),
        source.content_hash is not None,
    )
