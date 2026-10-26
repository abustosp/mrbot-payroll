"""Decimal conversion and payroll rounding helpers."""

from __future__ import annotations

from decimal import (
    ROUND_DOWN,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    ROUND_UP,
    Decimal,
    DecimalException,
    localcontext,
)
from typing import Any

from app.core.payroll_engine.types import RoundingPolicy

_ROUNDING_MODES = {
    "HALF_UP": ROUND_HALF_UP,
    "HALF_EVEN": ROUND_HALF_EVEN,
    "DOWN": ROUND_DOWN,
    "UP": ROUND_UP,
}


def to_decimal(value: Any) -> Decimal:
    """Convert supported exact inputs, rejecting binary floats and non-finite values."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"expected Decimal, integer, or decimal string; got {type(value).__name__}")
    if isinstance(value, Decimal):
        result = value
    elif isinstance(value, int):
        result = Decimal(value)
    elif isinstance(value, str):
        try:
            result = Decimal(value.strip())
        except DecimalException as exc:
            raise ValueError(f"invalid decimal value {value!r}") from exc
    else:
        raise ValueError(f"expected Decimal, integer, or decimal string; got {type(value).__name__}")
    if not result.is_finite():
        raise ValueError("Decimal value must be finite")
    return result


def quantize(value: Any, policy: RoundingPolicy) -> Decimal:
    """Quantize an exact value using the configured payroll rounding policy."""
    decimal_value = to_decimal(value)
    mode = str(policy.mode)
    rounding = _ROUNDING_MODES.get(mode)
    if rounding is None:
        raise ValueError(f"unsupported rounding mode {mode!r}")
    decimals = policy.decimals
    if isinstance(decimals, bool) or not isinstance(decimals, int) or decimals < 0:
        raise ValueError("rounding decimals must be a non-negative integer")
    quantum = Decimal(1).scaleb(-decimals)
    # Quantize needs enough precision to retain all integer digits as well as the scale.
    precision = max(28, len(decimal_value.as_tuple().digits), decimal_value.adjusted() + decimals + 2)
    try:
        with localcontext() as context:
            context.prec = precision
            return decimal_value.quantize(quantum, rounding=rounding)
    except DecimalException as exc:
        raise ValueError(f"cannot round {decimal_value} to {decimals} decimal places") from exc
