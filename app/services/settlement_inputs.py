"""Typed employee inputs for special runs; values are persisted as JSON strings."""
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SettlementInputs(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)

    @model_validator(mode="before")
    @classmethod
    def reject_binary_money(cls, value):
        if isinstance(value, dict):
            for key in ("worked_days", "worked_base_salary", "notice_base_salary", "vacation_days",
                        "vacation_base_salary", "indemnity_base_salary", "indemnity_cap", "preaviso_months"):
                if isinstance(value.get(key), (float, bool)):
                    raise ValueError(f"{key} requiere una cadena decimal o entero exacto")
        return value

    cause: Literal["RENUNCIA", "DESPIDO_SIN_CAUSA"] | None = None
    worked_days: Decimal | None = Field(default=None, ge=0, le=30)
    worked_base_salary: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    notice_base_salary: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    other_entitlements_reviewed: bool | None = Field(default=None, strict=True)
    vacation_days: Decimal | None = Field(default=None, ge=0, le=366)
    vacation_base_salary: Decimal | None = Field(default=None, ge=0, max_digits=18, decimal_places=4)
    sac_excluded_days: int | None = Field(default=None, ge=0, le=184, strict=True)
    indemnity_base_salary: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    indemnity_cap: Decimal | None = Field(default=None, gt=0, max_digits=18, decimal_places=4)
    preaviso_months: Decimal | None = Field(default=None, ge=0, le=2)
    integration_days: int | None = Field(default=None, ge=0, le=30, strict=True)
    probation: bool | None = Field(default=None, strict=True)
    without_notice: bool | None = Field(default=None, strict=True)
