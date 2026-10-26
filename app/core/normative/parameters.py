"""Pure helpers for parameters with inclusive validity dates."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum


class ParameterStatus(StrEnum):
    DEMO = "demo"
    DRAFT = "draft"
    APPROVED = "approved"
    OBSOLETE = "obsolete"


@dataclass(frozen=True, slots=True)
class ParameterVersion:
    code: str
    value: Decimal
    valid_from: date
    valid_to: date | None = None
    published_at: date | None = None
    source: str = ""
    version: int = 1
    status: str = ParameterStatus.DRAFT

    def __post_init__(self) -> None:
        code = self.code.strip()
        if not code:
            raise ValueError("parameter code cannot be blank")
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError("valid_to cannot be earlier than valid_from")
        if self.version < 1:
            raise ValueError("parameter version must be at least 1")
        try:
            value = self.value if isinstance(self.value, Decimal) else Decimal(str(self.value))
        except (InvalidOperation, ValueError):
            raise ValueError("parameter value must be a finite Decimal") from None
        if not value.is_finite():
            raise ValueError("parameter value must be a finite Decimal")
        object.__setattr__(self, "code", code)
        object.__setattr__(self, "value", value)


def _overlaps(left: ParameterVersion, right: ParameterVersion) -> bool:
    return (
        left.code == right.code
        and (left.valid_to is None or right.valid_from <= left.valid_to)
        and (right.valid_to is None or left.valid_from <= right.valid_to)
    )


def find_overlaps(
    parameters: Iterable[ParameterVersion],
) -> list[tuple[ParameterVersion, ParameterVersion]]:
    """Return every same-code pair with intersecting inclusive validity dates."""
    by_code: dict[str, list[ParameterVersion]] = {}
    for parameter in parameters:
        by_code.setdefault(parameter.code, []).append(parameter)
    overlaps: list[tuple[ParameterVersion, ParameterVersion]] = []
    for versions in by_code.values():
        versions.sort(key=lambda item: (item.valid_from, item.valid_to or date.max))
        for index, left in enumerate(versions):
            for right in versions[index + 1 :]:
                if left.valid_to is not None and right.valid_from > left.valid_to:
                    break
                if _overlaps(left, right):
                    overlaps.append((left, right))
    return overlaps


def validate_no_overlaps(parameters: Iterable[ParameterVersion]) -> None:
    overlaps = find_overlaps(parameters)
    if overlaps:
        left, right = overlaps[0]
        raise ValueError(
            f"overlapping versions for {left.code}: "
            f"{left.valid_from}..{left.valid_to or 'open'} and "
            f"{right.valid_from}..{right.valid_to or 'open'}"
        )


def select_parameter(
    parameters: Iterable[ParameterVersion],
    code: str,
    on_date: date,
    *,
    status: str | None = None,
) -> ParameterVersion:
    """Select one parameter effective on ``on_date``; both endpoints are inclusive."""
    versions = tuple(parameters)
    validate_no_overlaps(versions)
    candidates = [
        item
        for item in versions
        if item.code == code
        and item.valid_from <= on_date
        and (item.valid_to is None or on_date <= item.valid_to)
        and (status is None or item.status == status)
    ]
    if not candidates:
        raise LookupError(f"no active parameter {code!r} on {on_date}")
    if len(candidates) != 1:
        raise ValueError(f"ambiguous parameter {code!r} on {on_date}")
    return candidates[0]


def select_parameters(
    parameters: Iterable[ParameterVersion],
    on_date: date,
    *,
    status: str | None = None,
) -> dict[str, ParameterVersion]:
    """Select all effective parameters, keyed by code."""
    versions = tuple(parameters)
    validate_no_overlaps(versions)
    return {
        item.code: item
        for item in versions
        if item.valid_from <= on_date
        and (item.valid_to is None or on_date <= item.valid_to)
        and (status is None or item.status == status)
    }
