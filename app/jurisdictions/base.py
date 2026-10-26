"""Common contract implemented by jurisdiction-specific rule providers."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from decimal import Decimal
from typing import Any, Protocol


class JurisdictionProvider(Protocol):
    code: str

    def get_applicable_rules(self, employee_id: str, period: date) -> list[Any]: ...

    def get_statutory_parameters(self, period: date) -> Mapping[str, Decimal]: ...

    def validate_payroll(self, payroll: Mapping[str, Any]) -> list[str]: ...

    def get_available_exports(self) -> tuple[str, ...]: ...
