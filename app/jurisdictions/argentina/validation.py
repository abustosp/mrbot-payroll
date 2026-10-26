"""Strict, dependency-free Argentina identifier and period validation."""

from __future__ import annotations

import re
from datetime import date

_SEPARATORS = re.compile(r"[-.\s]")
_PERIOD = re.compile(r"[0-9]{6}", flags=re.ASCII)
_WEIGHTS = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)


def normalize_cuit_cuil(value: object) -> str:
    text = "" if value is None else str(value).strip()
    canonical = _SEPARATORS.sub("", text)
    if len(canonical) != 11 or not canonical.isascii() or not canonical.isdigit():
        raise ValueError("CUIT/CUIL debe tener 11 dígitos ASCII.")
    total = sum(
        int(digit) * weight
        for digit, weight in zip(canonical[:10], _WEIGHTS, strict=True)
    )
    remainder = 11 - total % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    if verifier != int(canonical[-1]):
        raise ValueError("CUIT/CUIL tiene un dígito verificador inválido.")
    return canonical


def is_valid_cuit_cuil(value: object) -> bool:
    try:
        normalize_cuit_cuil(value)
    except ValueError:
        return False
    return True


def parse_period(value: date | str) -> date:
    """Return the first day of a payroll month from a date or ``AAAAMM``."""
    if isinstance(value, date):
        return value.replace(day=1)
    text = str(value)
    if not _PERIOD.fullmatch(text):
        raise ValueError("El período debe tener formato AAAAMM.")
    year, month = int(text[:4]), int(text[4:])
    try:
        return date(year, month, 1)
    except ValueError:
        raise ValueError("El período debe tener un mes entre 01 y 12.") from None


def validate_period(value: date | str) -> str:
    return parse_period(value).strftime("%Y%m")
