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

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import AliasChoices, BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict, get_scoped
from app.auth.dependencies import require_role, require_user
from app.config import get_settings
from app.core.payroll_engine import settlements as settlement_engine
from app.core.payroll_engine.settlements import SettlementError
from app.database.models import (
    AuditLog,
    Employee,
    EmploymentContract,
    PayrollRun,
    PayrollSettlementInput,
    User,
)
from app.database.session import get_db
from app.services.settlement_inputs import SettlementInputs

router = APIRouter(prefix="/settlements", tags=["settlements"])


@router.get("/runs/{run_id}/employees/{employee_id}/inputs", response_model=SettlementInputs)
def get_settlement_inputs(run_id: int, employee_id: int, db: Session = Depends(get_db),
                          user: User = Depends(require_user)):
    run = get_scoped(db, PayrollRun, run_id, user.organization_id)
    _scoped_employee(db, run, employee_id)
    row = db.scalar(select(PayrollSettlementInput).where(
        PayrollSettlementInput.payroll_run_id == run.id,
        PayrollSettlementInput.employee_id == employee_id))
    return SettlementInputs.model_validate(row.values if row else {})


def _scoped_employee(db: Session, run: PayrollRun, employee_id: int) -> Employee:
    employee = db.scalar(select(Employee).join(EmploymentContract,
        EmploymentContract.employee_id == Employee.id).where(
        Employee.id == employee_id, Employee.organization_id == run.organization_id,
        EmploymentContract.company_id == run.company_id,
        EmploymentContract.valid_from <= run.period_end,
        (EmploymentContract.valid_to.is_(None) | (EmploymentContract.valid_to >= run.period_start))))
    if employee is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado en la empresa y período")
    return employee


@router.put("/runs/{run_id}/employees/{employee_id}/inputs", response_model=SettlementInputs)
def put_settlement_inputs(run_id: int, employee_id: int, payload: SettlementInputs, request: Request,
                          db: Session = Depends(get_db), user: User = Depends(require_role("admin", "editor"))):
    from app.web.auth import enforce_csrf
    enforce_csrf(request, "", get_settings(), user.id)
    return save_settlement_inputs(db, run_id, employee_id, payload, user)


def save_settlement_inputs(db: Session, run_id: int, employee_id: int,
                           payload: SettlementInputs, user: User) -> SettlementInputs:
    run = get_scoped(db, PayrollRun, run_id, user.organization_id)
    if run.run_type not in {"SAC", "VACATIONS", "FINAL"}:
        raise HTTPException(status_code=422, detail="La corrida no admite insumos de liquidación especial")
    _scoped_employee(db, run, employee_id)
    claim = db.execute(update(PayrollRun).where(PayrollRun.id == run.id,
        PayrollRun.status == "DRAFT").values(status="DRAFT", inputs_hash=None, results_hash=None, ruleset_id=None))
    if not isinstance(claim, CursorResult) or claim.rowcount != 1:
        db.rollback()
        raise HTTPException(status_code=409, detail="Reabra la corrida antes de modificar insumos")
    row = db.scalar(select(PayrollSettlementInput).where(
        PayrollSettlementInput.payroll_run_id == run.id, PayrollSettlementInput.employee_id == employee_id))
    values = payload.model_dump(mode="json", exclude_none=True)
    before = dict(row.values) if row else None
    if row is None:
        db.add(PayrollSettlementInput(payroll_run_id=run.id, employee_id=employee_id, values=values))
    else:
        row.values = values
    from app.services.payroll_calculation import _clear_previous_results
    _clear_previous_results(db, run.id)
    db.add(AuditLog(organization_id=user.organization_id, user_id=user.id,
        action="settlement_inputs.updated", entity_type="PayrollRun", entity_id=str(run.id),
        before={"employee_id": employee_id, "values": before},
        after={"employee_id": employee_id, "values": values}))
    commit_or_conflict(db)
    return payload


class _ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class SacInput(BaseModel):
    """Datos para calcular el SAC de un período."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "period": "2026-06-30",
        "months_worked": "6",
        "remunerations": ["1000000", "1200000", "1100000"],
    }]})

    period: date = Field(description="Fecha de cierre del período de SAC.")
    months_worked: Decimal = Field(ge=0, description="Meses de devengamiento ya determinados.")
    remunerations: list[Decimal] | None = Field(
        default=None,
        description="Remuneraciones del semestre; se usa la mejor como base.",
    )
    best_salary: Decimal | None = Field(
        default=None,
        ge=0,
        validation_alias=AliasChoices("best_salary", "base_salary"),
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

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "monthly_salary": "750000",
        "days": "10",
        "days_base": "25",
        "plus_rate": "0.20",
    }]})

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

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "inputs": {
            "period": "2026-06-30",
            "monthly_salary": "1200000",
            "integration_days": "15",
            "vacation_days": "10",
            "sac_months_worked": "6",
            "sac_remunerations": ["1100000", "1200000"],
            "years_of_service": "5",
            "seniority_base_salary": "1200000",
        },
        "parameters": {
            "preaviso_months": "1",
            "month_integration_days_base": "30",
            "vacation_days_base": "25",
            "vacation_plus_rate": "0.20",
            "seniority_months_per_year": "1",
        },
    }]})

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
