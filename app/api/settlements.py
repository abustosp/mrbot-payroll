# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
"""Endpoints HTTP para SAC, vacaciones y liquidación final.

La capa es un envoltorio fino y autenticado de
:mod:`app.core.payroll_engine.settlements`. No persiste liquidaciones y no
aplica parámetros legales por defecto: cada dato normativo debe llegar en el
request. Los importes se reciben y devuelven como ``Decimal``/string y las
fechas como ISO ``YYYY-MM-DD``.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from app.auth.dependencies import require_user
from app.core.payroll_engine import settlements as settlement_engine
from app.core.payroll_engine.settlements import SettlementError
from app.database.models import User

router = APIRouter(prefix="/settlements", tags=["settlements"])


class _ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SacInput(BaseModel):
    """Datos para calcular el SAC de un período."""

    period: date = Field(description="Fecha de cierre del período de SAC.")
    months_worked: Decimal = Field(ge=0, description="Meses de devengamiento ya determinados.")
    remunerations: list[Decimal] | None = Field(
        default=None,
        description="Remuneraciones del semestre; se usa la mejor como base.",
    )
    best_salary: Decimal | None = Field(
        default=None,
        ge=0,
        description="Base explícita que reemplaza al máximo de remunerations.",
    )
    days_worked: Decimal | None = Field(
        default=None,
        ge=0,
        description="Días adicionales para el prorrateo proporcional.",
    )
    days_base: Decimal | None = Field(
        default=None,
        gt=0,
        description="Días base del mes; obligatorio junto con days_worked.",
    )


class VacationInput(BaseModel):
    """Datos para calcular el pago de vacaciones."""

    monthly_salary: Decimal = Field(ge=0, description="Salario mensual.")
    days: Decimal = Field(ge=0, description="Días de vacaciones a liquidar.")
    days_base: Decimal = Field(
        default=Decimal("25"),
        gt=0,
        description="Días base para el valor diario.",
    )
    # B-29: omitido (None) liquida plus 0 con aviso en warnings; 0 explícito
    # declara que no corresponde plus (el default por CCT sigue en D-6).
    plus_rate: Decimal | None = Field(
        default=None,
        ge=0,
        description="Plus como fracción del importe base (0.20 = 20 %).",
    )


class FinalSettlementInputs(BaseModel):
    """Datos del trabajador y del período para la liquidación final."""

    period: date = Field(description="Fecha de la liquidación final.")
    monthly_salary: Decimal = Field(ge=0, description="Salario mensual.")
    integration_days: Decimal = Field(ge=0, description="Días del mes a integrar.")
    vacation_days: Decimal = Field(ge=0, description="Días de vacaciones no gozadas.")
    sac_months_worked: Decimal = Field(ge=0, description="Meses de SAC devengados.")
    years_of_service: Decimal = Field(ge=0, description="Años de servicio.")
    seniority_base_salary: Decimal = Field(
        ge=0,
        description="Salario base explícito de la indemnización por antigüedad.",
    )
    sac_remunerations: list[Decimal] | None = Field(
        default=None,
        description="Remuneraciones del semestre para el SAC proporcional.",
    )
    sac_best_salary: Decimal | None = Field(
        default=None,
        ge=0,
        description="Base explícita del SAC proporcional.",
    )
    sac_days_worked: Decimal | None = Field(
        default=None,
        ge=0,
        description="Días adicionales de SAC; requiere parameters.sac_days_base.",
    )


class FinalSettlementParameters(BaseModel):
    """Parámetros normativos explícitos; no se aplican valores legales por defecto."""

    preaviso_months: Decimal = Field(ge=0, description="Meses de preaviso.")
    month_integration_days_base: Decimal = Field(
        gt=0,
        description="Días base para la integración del mes.",
    )
    vacation_days_base: Decimal = Field(
        gt=0,
        description="Días base para el valor diario de vacaciones.",
    )
    vacation_plus_rate: Decimal = Field(
        ge=0,
        description="Plus de vacaciones como fracción; 0 si no corresponde.",
    )
    seniority_months_per_year: Decimal = Field(
        ge=0,
        description="Meses de salario por año de servicio.",
    )
    sac_days_base: Decimal | None = Field(
        default=None,
        gt=0,
        description="Días base del SAC; obligatorio si se informa sac_days_worked.",
    )


class FinalSettlementRequest(BaseModel):
    """Payload de liquidación final, separado en datos y parámetros."""

    inputs: FinalSettlementInputs
    parameters: FinalSettlementParameters


class SacResponse(_ResponseModel):
    period: date
    base: Decimal
    months_worked: Decimal
    days_worked: Decimal | None
    effective_months: Decimal
    amount: Decimal
    trace: list[str]


class VacationResponse(_ResponseModel):
    monthly_salary: Decimal
    days: Decimal
    days_base: Decimal
    daily_value: Decimal
    plus_rate: Decimal
    base_amount: Decimal
    plus_amount: Decimal
    amount: Decimal
    trace: list[str]
    warnings: list[str] = []


class SettlementItemResponse(_ResponseModel):
    code: str
    name: str
    nature: str
    amount: Decimal
    quantity: Decimal | None
    unit: str | None
    trace: list[str]


class FinalSettlementResponse(_ResponseModel):
    period: date
    items: list[SettlementItemResponse]
    total: Decimal
    remunerative_total: Decimal
    non_remunerative_total: Decimal
    trace: list[str]


def _invalid_settlement(exc: SettlementError) -> HTTPException:
    """Convert an engine validation error into a FastAPI 422 response."""

    return HTTPException(
        status_code=422,
        detail=f"Liquidación inválida: {exc}",
    )


@router.post("/sac", response_model=SacResponse)
def calculate_sac_endpoint(
    payload: SacInput,
    _user: User = Depends(require_user),
) -> SacResponse:
    """Calculate SAC from caller-supplied remunerations and period data."""

    try:
        result = settlement_engine.calculate_sac(
            payload.remunerations,
            payload.period,
            months_worked=payload.months_worked,
            best_salary=payload.best_salary,
            days_worked=payload.days_worked,
            days_base=payload.days_base,
        )
    except SettlementError as exc:
        raise _invalid_settlement(exc) from exc
    return SacResponse.model_validate(result)


@router.post("/vacations", response_model=VacationResponse)
def calculate_vacations_endpoint(
    payload: VacationInput,
    _user: User = Depends(require_user),
) -> VacationResponse:
    """Calculate vacation pay including an optional configurable plus."""

    try:
        result = settlement_engine.calculate_vacations(
            payload.monthly_salary,
            payload.days,
            days_base=payload.days_base,
            plus_rate=payload.plus_rate,
        )
    except SettlementError as exc:
        raise _invalid_settlement(exc) from exc
    return VacationResponse.model_validate(result)


@router.post("/final", response_model=FinalSettlementResponse)
def calculate_final_settlement_endpoint(
    payload: FinalSettlementRequest,
    _user: User = Depends(require_user),
) -> FinalSettlementResponse:
    """Calculate the independent components and totals of a final settlement."""

    inputs = payload.inputs.model_dump(exclude_none=True)
    parameters = payload.parameters.model_dump()
    try:
        result = settlement_engine.calculate_final_settlement(inputs, parameters)
    except SettlementError as exc:
        raise _invalid_settlement(exc) from exc
    return FinalSettlementResponse(
        period=result.period,
        items=[
            SettlementItemResponse(
                code=item.code,
                name=item.name,
                nature=item.nature.value,
                amount=item.amount,
                quantity=item.quantity,
                unit=item.unit,
                trace=list(item.trace),
            )
            for item in result.items
        ],
        total=result.total,
        remunerative_total=result.remunerative_total,
        non_remunerative_total=result.non_remunerative_total,
        trace=list(result.trace),
    )


__all__ = [
    "FinalSettlementRequest",
    "FinalSettlementResponse",
    "SacInput",
    "SacResponse",
    "VacationInput",
    "VacationResponse",
    "router",
]
