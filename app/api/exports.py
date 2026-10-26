# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from datetime import date
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.auth.dependencies import require_user
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.exporters.pdf.receipts import (
    PdfRendererUnavailable,
    ReceiptContextError,
    ReceiptError,
    render_receipt_pdf,
)
from app.exporters.txt.lsd import (
    LAYOUT_VERSION,
    generate_concepts_file,
    generate_liquidation_file,
)

router = APIRouter(prefix="/exports", tags=["exports"])


class LiquidationExportInput(BaseModel):
    employer_cuit: str
    period: date | str
    workers: list[dict[str, Any]] = Field(min_length=1)
    liquidation_number: int = Field(default=1, ge=1, le=99999)


class ConceptsExportInput(BaseModel):
    concepts: list[dict[str, Any]] = Field(min_length=1)


def _text_file(payload: bytes, filename: str) -> Response:
    return Response(
        content=payload,
        media_type="text/plain; charset=latin-1",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


@router.post(
    "/lsd/liquidations",
    response_class=Response,
    description=(
        "Genera el archivo LSD de liquidaciones (layout fijo borrador "
        f"version {LAYOUT_VERSION}; la version no viaja dentro del contenido). "
        "Borrador interno sin validez ante ARCA. "
        "Ejemplo de payload valido: "
        '{"employer_cuit": "30-12345678-1", "period": "202601", '
        '"liquidation_number": 1, "workers": [{"cuil": "20-12345678-6", '
        '"legajo": "A1", "pay_date": "2026-01-31", "rubric_date": "2026-01-31", '
        '"items": [{"concept_code": "BASICO", "quantity": 1, "amount": "100000.00"}], '
        '"record04": {}}]}.'
    ),
)
def export_lsd_liquidations(
    payload: LiquidationExportInput,
    _user: User = Depends(require_user),
) -> Response:
    try:
        content = generate_liquidation_file(
            payload.employer_cuit,
            payload.period,
            payload.workers,
            liquidation_number=payload.liquidation_number,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Liquidación LSD inválida: {exc}") from exc
    return _text_file(content, "liquidaciones-borrador-sin-validez-arca.txt")


@router.post(
    "/lsd/concepts",
    response_class=Response,
    description=(
        "Genera el archivo LSD de conceptos (layout fijo borrador "
        f"version {LAYOUT_VERSION}; la version no viaja dentro del contenido). "
        "Borrador interno sin validez ante ARCA. "
        "Ejemplo de payload valido: "
        '{"concepts": [{"arca_code": "001", "employer_code": "BASICO", '
        '"description": "Sueldo basico"}]} '
        "(arca_code de 3 digitos, employer_code hasta 10, description hasta 50)."
    ),
)
def export_lsd_concepts(
    payload: ConceptsExportInput,
    _user: User = Depends(require_user),
) -> Response:
    try:
        content = generate_concepts_file(payload.concepts)
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"Conceptos LSD inválidos: {exc}") from exc
    return _text_file(content, "conceptos-borrador-sin-validez-arca.txt")


@router.post("/receipts/{result_id}", response_class=Response)
def export_receipt(
    result_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> Response:
    result = db.scalar(
        select(PayrollResult)
        .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
        .where(
            PayrollResult.id == result_id,
            PayrollRun.organization_id == user.organization_id,
        )
    )
    if result is None:
        raise HTTPException(status_code=404, detail="Resultado de liquidación no encontrado")

    run = db.get(PayrollRun, result.payroll_run_id)
    employee = db.get(Employee, result.employee_id)
    company = db.get(Company, run.company_id) if run else None
    if run is None or employee is None or company is None:
        raise HTTPException(status_code=404, detail="Datos del recibo no encontrados")

    contract = db.scalar(
        select(EmploymentContract)
        .where(
            EmploymentContract.employee_id == employee.id,
            EmploymentContract.company_id == company.id,
            EmploymentContract.valid_from <= run.period_end,
            or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= run.period_end),
        )
        .order_by(EmploymentContract.valid_from.desc())
    )
    category = db.get(AgreementCategory, contract.category_id) if contract and contract.category_id else None
    agreement = (
        db.get(CollectiveAgreement, contract.agreement_id)
        if contract and contract.agreement_id
        else None
    )
    items = db.scalars(
        select(PayrollItem)
        .where(PayrollItem.payroll_result_id == result.id)
        .order_by(PayrollItem.id)
    ).all()
    kinds = {
        "REMUNERATIVE": "remunerative",
        "NON_REMUNERATIVE": "non_remunerative",
        "DEDUCTION": "deduction",
        "CONTRIBUTION": "contribution",
    }
    context = {
        "receipt_number": f"{run.code}-{employee.employee_code}",
        "issue_date": run.period_end,
        "period": run.period_end.strftime("%m/%Y"),
        "employer": {
            "name": company.legal_name,
            "cuit": company.cuit,
            "address": company.address,
            "activity": company.tax_activity,
        },
        "employee": {
            "name": f"{employee.first_name} {employee.last_name}".strip(),
            "cuil": employee.cuil,
            "file_number": employee.employee_code,
            "category": category.name if category else "",
            "hire_date": employee.hire_date,
            "agreement": agreement.code if agreement else "",
        },
        "items": [
            {
                "code": item.code,
                "name": item.description,
                "kind": kinds[item.nature],
                "quantity": item.quantity,
                "unit": "",
                "amount": str(item.amount),
            }
            for item in items
            if item.nature in kinds
        ],
        "remunerative_total": str(result.remunerative),
        "non_remunerative_total": str(result.non_remunerative),
        "deductions_total": str(result.deductions),
        "contributions_total": str(result.contributions),
        "net": str(result.net),
    }
    try:
        content = render_receipt_pdf(context)
    except ReceiptContextError as exc:
        raise HTTPException(status_code=422, detail=f"Datos del recibo inválidos: {exc}") from exc
    except PdfRendererUnavailable as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ReceiptError as exc:
        raise HTTPException(status_code=500, detail="No se pudo generar el PDF del recibo") from exc
    return Response(
        content=content,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="recibo-{result.id}.pdf"',
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "private, no-store",
        },
    )


__all__ = ["router"]
