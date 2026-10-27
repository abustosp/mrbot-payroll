# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
"""Alta real de contratos de trabajo (V2-26).

Schemas autocontenidos en este módulo. Valida vigencia
(``valid_to`` igual o posterior a ``valid_from``) y solape con otro
contrato activo del mismo empleado y empresa (409).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.auth.dependencies import require_role
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    User,
)
from app.database.session import get_db

router = APIRouter(prefix="/contracts", tags=["contracts"])


class ContractInput(BaseModel):
    """Alta de contrato; sin defaults legales, solo vigencia y solape."""

    employee_id: int
    company_id: int
    agreement_id: int | None = None
    category_id: int | None = None
    valid_from: date
    valid_to: date | None = None
    employment_type: str = Field(default="full_time", max_length=40)
    weekly_hours: Decimal | None = Field(default=None, ge=0)
    monthly_salary: Decimal | None = Field(default=None, ge=0)

    @field_validator("valid_to")
    @classmethod
    def validity_is_inclusive(cls, value: date | None, info):  # type: ignore[no-untyped-def]
        start = info.data.get("valid_from")
        if value is not None and start is not None and value < start:
            raise ValueError("valid_to debe ser igual o posterior a valid_from")
        return value


class ContractRead(BaseModel):
    """Contrato persistido."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    employee_id: int
    company_id: int
    agreement_id: int | None
    category_id: int | None
    valid_from: date
    valid_to: date | None
    employment_type: str
    weekly_hours: Decimal | None
    monthly_salary: Decimal | None
    active: bool


@router.post("", response_model=ContractRead, status_code=status.HTTP_201_CREATED)
def create_contract(
    payload: ContractInput,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Create a contract after vigencia and overlap validation (V2-26)."""
    employee = db.scalar(
        select(Employee).where(
            Employee.id == payload.employee_id,
            Employee.organization_id == user.organization_id,
        )
    )
    if employee is None:
        raise HTTPException(status_code=404, detail="Empleado no encontrado")
    company = db.scalar(
        select(Company).where(
            Company.id == payload.company_id,
            Company.organization_id == user.organization_id,
        )
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Empresa no encontrada")
    if payload.agreement_id is not None and (
        db.scalar(select(CollectiveAgreement.id).where(
            CollectiveAgreement.id == payload.agreement_id
        )) is None
    ):
        raise HTTPException(status_code=422, detail="Convenio inexistente")
    if payload.category_id is not None:
        category_statement = select(AgreementCategory.id).where(
            AgreementCategory.id == payload.category_id
        )
        if payload.agreement_id is not None:
            category_statement = category_statement.where(
                AgreementCategory.agreement_id == payload.agreement_id
            )
        if db.scalar(category_statement) is None:
            raise HTTPException(status_code=422, detail="Categoría inexistente")
    window_end = payload.valid_to or date.max
    overlap = db.scalar(
        select(EmploymentContract.id).where(
            EmploymentContract.employee_id == payload.employee_id,
            EmploymentContract.company_id == payload.company_id,
            EmploymentContract.active.is_(True),
            EmploymentContract.valid_from <= window_end,
            or_(
                EmploymentContract.valid_to.is_(None),
                EmploymentContract.valid_to >= payload.valid_from,
            ),
        )
    )
    if overlap is not None:
        raise HTTPException(
            status_code=409,
            detail="Existe un contrato activo solapado para el empleado y la empresa",
        )
    row = EmploymentContract(
        employee_id=payload.employee_id,
        company_id=payload.company_id,
        agreement_id=payload.agreement_id,
        category_id=payload.category_id,
        valid_from=payload.valid_from,
        valid_to=payload.valid_to,
        employment_type=payload.employment_type,
        weekly_hours=payload.weekly_hours,
        monthly_salary=payload.monthly_salary,
        active=True,
    )
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


__all__ = ["ContractInput", "ContractRead", "router"]
