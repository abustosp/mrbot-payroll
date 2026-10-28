# ruff: noqa: B008 -- FastAPI resolves File/Depends defaults at request time.
"""API de importacion de empleados y novedades desde CSV/XLSX.

Los endpoints reutilizan los importadores puros de ``app.importers``: primero
se arma un :class:`~app.importers.models.ImportPreview` y, en los commits, se
revalidan las filas con ``import_rows`` antes de persistirlas. El ``dry_run``
es el modo por defecto, por lo que un pedido sin ``dry_run=false`` nunca
modifica la base de datos.

Contrato HTTP (B-47P): preview y commit responden **HTTP 200** con
``valid_rows`` + ``errors[]`` + ``duplicates[]`` + ``warnings[]`` (incluye
``formula_riesgosa``); **no** usan 422 por fila. Los 400/413/422 quedan para
archivo invalido (extension, vacio, binario, limite 5 MB, XLSX corrupto). Cada
``errors[]`` trae ``row/field/code/message``; ``cuil_invalido`` exige 11
digitos (p. ej. 20-12345678-6) y ``columna_faltante`` cita la cabecera valida
(``Legajo;Apellido;Nombre;CUIL;Fecha de ingreso`` o
``Legajo;Periodo;Tipo;Cantidad;Importe;Observacion``). ``<``/``>`` en campos
libres se rechazan con ``caracteres_no_permitidos`` (V2-13).

El commit de **novedades** persiste las filas validas en
``payroll_novelties`` y es idempotente por la clave natural
``(employee_id, company_id, period, code, source)``. Los legajos se resuelven dentro de la
organizacion del usuario; una fila cuyo legajo no existe se informa como error
sin abortar el resto del lote. ``company_id`` es opcional y, si se informa, se
valida que la empresa pertenezca a la organizacion y tenga contrato en el mes;
si se omite, debe existir una sola empresa contractual.
"""

from __future__ import annotations

import io
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import Field
from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.common import commit_or_conflict
from app.api.payroll_runs import AnnulInput
from app.auth.dependencies import require_role, require_user
from app.database.models import (
    AuditLog,
    Company,
    Employee,
    EmploymentContract,
    PayrollConcept,
    PayrollNovelty,
    PayrollRun,
    User,
)
from app.database.session import get_db
from app.importers.models import (
    ConceptRow,
    DuplicateRow,
    EmployeeRow,
    ImportPreview,
    ImportResult,
    NoveltyRow,
    RowError,
)
from app.importers.readers import ImportFileError
from app.importers.service import analyze_file, import_rows
from app.services.payroll_calculation import _clear_previous_results

router = APIRouter(prefix="/imports", tags=["imports"])

MAX_IMPORT_BYTES = 5 * 1024 * 1024
ALLOWED_SUFFIXES = frozenset({".csv", ".xlsx", ".xlsm"})
COMMIT_ROLES = frozenset({"admin", "editor"})
NOVELTY_SOURCE = "import"
# B-43: la naturaleza llega por novedad (columna opcional Naturaleza, default
# REMUNERATIVE). Sin migracion: la quincena no se persiste; el preview avisa
# con quincena_pendiente.
NOVELTY_KIND = "REMUNERATIVE"


class RepairNoveltyInput(AnnulInput):
    company_id: int = Field(gt=0)


def _invalidate_runs(db: Session, user: User, runs: Sequence[PayrollRun], reason: str) -> None:
    for run in runs:
        if run.status in {"CALCULATED", "IN_REVIEW", "ERROR"}:
            before = run.status
            run.status = "DRAFT"
            run.inputs_hash = run.results_hash = run.ruleset_id = None
            _clear_previous_results(db, run.id)
            db.add(AuditLog(
                organization_id=user.organization_id, user_id=user.id,
                action="payroll_run.reopened", entity_type="PayrollRun", entity_id=str(run.id),
                before={"status": before}, after={"status": "DRAFT", "reason": reason},
            ))


class _NamedBytesIO(io.BytesIO):
    """``BytesIO`` con nombre para que el reader detecte la extension."""

    def __init__(self, content: bytes, name: str) -> None:
        super().__init__(content)
        self.name = name


def _serialize(outcome: ImportPreview | ImportResult, **extra: Any) -> dict[str, Any]:
    """Serializa un preview/resultado e incorpora los conteos derivados."""
    payload = outcome.model_dump(mode="json")
    payload.update(
        valid_count=outcome.valid_count,
        error_count=outcome.error_count,
        duplicate_count=outcome.duplicate_count,
    )
    payload.update(extra)
    return payload


def _read_upload(upload: UploadFile) -> tuple[bytes, str]:
    """Lee y valida extension, tamano, encoding basico y contenido vacio."""
    filename = (upload.filename or "").strip()
    suffix = Path(filename).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Extension no soportada. Adjunte un archivo .csv, .xlsx o .xlsm.",
        )

    upload.file.seek(0)
    content = upload.file.read(MAX_IMPORT_BYTES + 1)
    if len(content) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "El archivo supera el tamano maximo permitido de "
                f"{MAX_IMPORT_BYTES // (1024 * 1024)} MB."
            ),
        )
    if not content or not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El archivo esta vacio.",
        )
    if suffix == ".csv" and b"\x00" in content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="El CSV contiene datos binarios o una codificacion no soportada.",
        )
    return content, filename


def _analyze(content: bytes, filename: str, kind: str) -> ImportPreview:
    """Ejecuta ``analyze_file`` preservando el nombre original del archivo."""
    stream = _NamedBytesIO(content, filename)
    try:
        return analyze_file(stream, kind)
    except ImportFileError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _ensure_commit_role(user: User) -> None:
    if user.role not in COMMIT_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Permiso insuficiente para confirmar una importacion.",
        )


def _scoped_company(db: Session, company_id: int, organization_id: int) -> Company:
    company = db.scalar(
        select(Company).where(
            Company.id == company_id,
            Company.organization_id == organization_id,
        )
    )
    if company is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Empresa no encontrada.",
        )
    return company


def _commit_employees(
    db: Session,
    user: User,
    preview: ImportPreview,
    company_id: int | None,
) -> dict[str, Any]:
    """Persiste las filas validas sin abortar el lote por filas con conflicto.

    La idempotencia se garantiza por ``(organization_id, employee_code)``: un
    legajo ya existente se informa como duplicado y no se vuelve a crear. Si se
    informa ``company_id`` se crea un contrato minimo por empleado nuevo; sin
    ese dato no se crean contratos y los empleados se importan igualmente.
    """
    result = import_rows(list(preview.valid_rows), "employees")
    result.total = preview.total
    result.errors = [*preview.errors, *result.errors]
    result.duplicates = [*preview.duplicates, *result.duplicates]
    result.dry_run = False

    company = (
        _scoped_company(db, company_id, user.organization_id) if company_id is not None else None
    )
    existing_codes = set(
        db.scalars(
            select(Employee.employee_code).where(Employee.organization_id == user.organization_id)
        ).all()
    )

    created = 0
    skipped = 0
    contracts_created = 0
    for index, row in enumerate(result.valid_rows):
        if not isinstance(row, EmployeeRow):
            continue
        row_number = index + 2
        if row.legajo in existing_codes:
            skipped += 1
            result.duplicates.append(
                DuplicateRow(
                    row=row_number,
                    first_row=row_number,
                    key=f"legajo:{row.legajo}",
                    message=(
                        "Ya existe un empleado con ese legajo en la organizacion; la fila se omite."
                    ),
                )
            )
            continue

        employee = Employee(
            organization_id=user.organization_id,
            employee_code=row.legajo,
            first_name=row.nombre,
            last_name=row.apellido,
            cuil=row.cuil,
            email=row.email,
            hire_date=row.fecha_ingreso,
        )
        contract_created = False
        try:
            with db.begin_nested():
                db.add(employee)
                db.flush()
                if company is not None:
                    db.add(
                        EmploymentContract(
                            employee_id=employee.id,
                            company_id=company.id,
                            valid_from=row.fecha_ingreso,
                        )
                    )
                    contract_created = True
        except IntegrityError:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field="legajo",
                    code="conflicto_bd",
                    message=(
                        "La fila entra en conflicto con un empleado existente "
                        "(legajo o CUIL duplicado)."
                    ),
                    value=row.legajo,
                )
            )
            continue

        existing_codes.add(row.legajo)
        created += 1
        if contract_created:
            contracts_created += 1

    commit_or_conflict(db)
    return _serialize(
        result,
        created=created,
        skipped=skipped,
        contracts_created=contracts_created,
    )


def _commit_concepts(
    db: Session,
    user: User,
    preview: ImportPreview,
) -> dict[str, Any]:
    """Persiste conceptos validos sin abortar el lote por filas con conflicto.

    La idempotencia se garantiza por ``(organization_id, code)``: un codigo
    ya existente se informa como duplicado y no se vuelve a crear.
    """

    result = import_rows(list(preview.valid_rows), "concepts")
    result.total = preview.total
    result.errors = [*preview.errors, *result.errors]
    result.duplicates = [*preview.duplicates, *result.duplicates]
    result.dry_run = False

    existing_codes = set(
        db.scalars(
            select(PayrollConcept.code).where(
                PayrollConcept.organization_id == user.organization_id
            )
        ).all()
    )

    created = 0
    skipped = 0
    for index, row in enumerate(result.valid_rows):
        if not isinstance(row, ConceptRow):
            continue
        row_number = index + 2
        if row.codigo in existing_codes:
            skipped += 1
            result.duplicates.append(
                DuplicateRow(
                    row=row_number,
                    first_row=row_number,
                    key=f"codigo:{row.codigo}",
                    message=(
                        "Ya existe un concepto con ese codigo en la organizacion; la fila se omite."
                    ),
                )
            )
            continue
        db.add(
            PayrollConcept(
                organization_id=user.organization_id,
                code=row.codigo,
                name=row.nombre,
                nature=row.naturaleza,
                description=row.descripcion,
                active=True,
            )
        )
        existing_codes.add(row.codigo)
        created += 1

    commit_or_conflict(db)
    return _serialize(result, created=created, skipped=skipped)


def _commit_novelties(
    db: Session,
    user: User,
    preview: ImportPreview,
    company_id: int | None,
) -> dict[str, Any]:
    """Persiste novedades validas sin abortar el lote por una fila con error.

    La idempotencia se garantiza por ``(employee_id, company_id, period, code, source)``.
    Una novedad ya importada se informa como duplicada y no se vuelve a crear;
    si dos filas compiten por la misma clave, el ``IntegrityError`` se aisla con
    un ``SAVEPOINT`` y se continua con las restantes. Los legajos se resuelven
    solo dentro de la organizacion del usuario.
    """
    result = import_rows(list(preview.valid_rows), "novelties")
    result.total = preview.total
    result.errors = [*preview.errors, *result.errors]
    result.duplicates = [*preview.duplicates, *result.duplicates]
    result.dry_run = False

    if company_id is not None:
        _scoped_company(db, company_id, user.organization_id)

    employees_by_code = {
        employee.employee_code: employee
        for employee in db.scalars(
            select(Employee).where(Employee.organization_id == user.organization_id)
        ).all()
    }
    # ponytail: serialize novelty batches per organization to keep company locks
    # ordered; narrow to candidate companies if batch throughput becomes limiting.
    company_ids = db.scalars(select(Company.id).where(
        Company.organization_id == user.organization_id,
    ).order_by(Company.id)).all()
    for locked_id in company_ids:
        db.scalar(select(Company).where(Company.id == locked_id).with_for_update())
        db.execute(update(Company).where(Company.id == locked_id).values(active=Company.active))
    periods = sorted({row.periodo for row in result.valid_rows if isinstance(row, NoveltyRow)})
    existing: set[tuple[int, int | None, str, str]] = set()
    if periods:
        existing = {
            (row[0], row[1], row[2], row[3])
            for row in db.execute(
                select(
                    PayrollNovelty.employee_id,
                    PayrollNovelty.company_id,
                    PayrollNovelty.period,
                    PayrollNovelty.code,
                ).where(
                    PayrollNovelty.organization_id == user.organization_id,
                    PayrollNovelty.source == NOVELTY_SOURCE,
                    PayrollNovelty.period.in_(periods),
                )
            )
        }

    created = 0
    skipped = 0
    for index, row in enumerate(result.valid_rows):
        if not isinstance(row, NoveltyRow):
            continue
        row_number = index + 2
        employee = employees_by_code.get(row.legajo)
        if employee is None:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field="legajo",
                    code="legajo_no_encontrado",
                    message=(
                        "No existe un empleado con ese legajo en la organizacion; la fila se omite."
                    ),
                    value=row.legajo,
                )
            )
            continue

        year, month = int(row.periodo[:4]), int(row.periodo[4:])
        month_start = date(year, month, 1)
        next_month = date(year + (month == 12), month % 12 + 1, 1)
        companies = set(
            db.scalars(
                select(EmploymentContract.company_id)
                .join(Company, Company.id == EmploymentContract.company_id)
                .where(
                    EmploymentContract.employee_id == employee.id,
                    Company.organization_id == user.organization_id,
                    EmploymentContract.valid_from < next_month,
                    or_(
                        EmploymentContract.valid_to.is_(None),
                        EmploymentContract.valid_to >= month_start,
                    ),
                )
            )
        )
        if company_id is not None and company_id not in companies or not companies:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field="legajo",
                    code="sin_contrato",
                    message="El empleado no tiene contrato en la empresa para el mes indicado.",
                    value=row.legajo,
                )
            )
            continue
        if company_id is None and len(companies) != 1:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field="legajo",
                    code="empresa_ambigua",
                    message="El empleado tiene contratos en varias empresas para el mes; indique company_id.",
                    value=row.legajo,
                )
            )
            continue
        resolved_company = company_id if company_id is not None else next(iter(companies))
        legacy_key = (employee.id, None, row.periodo, row.tipo)
        if legacy_key in existing and len(companies) != 1:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field="legajo",
                    code="empresa_ambigua",
                    message="La novedad histórica no tiene empresa y sus contratos del mes son ambiguos.",
                    value=row.legajo,
                )
            )
            continue
        key = (employee.id, resolved_company, row.periodo, row.tipo)
        if key in existing or legacy_key in existing:
            skipped += 1
            result.duplicates.append(
                DuplicateRow(
                    row=row_number,
                    first_row=row_number,
                    key=(f"legajo:{row.legajo}|periodo:{row.periodo}|tipo:{row.tipo}"),
                    message=(
                        "Ya existe una novedad con el mismo legajo, periodo, tipo "
                        "y origen; la fila se omite."
                    ),
                )
            )
            continue

        # Lock even DRAFT rows: calculation/approval claims use conditional
        # updates on these same rows, so they cannot race this transaction.
        runs = db.scalars(
            select(PayrollRun)
            .where(
                PayrollRun.organization_id == user.organization_id,
                PayrollRun.company_id == resolved_company,
                PayrollRun.period_end >= month_start,
                PayrollRun.period_end < next_month,
            )
            .order_by(PayrollRun.id)
            .with_for_update()
        ).all()
        for run in runs:
            db.execute(
                update(PayrollRun).where(PayrollRun.id == run.id).values(status=PayrollRun.status)
            )
            db.refresh(run)
        blocked = next(
            (run for run in runs if run.status in {"APPROVED", "CLOSED", "VALIDATING"}), None
        )
        if blocked:
            skipped += 1
            calculating = blocked.status == "VALIDATING"
            result.errors.append(
                RowError(
                    row=row_number,
                    field="periodo",
                    code="liquidacion_en_calculo" if calculating else "liquidacion_bloqueada",
                    message=(
                        "La liquidación está en cálculo; vuelva a intentar al terminar."
                        if calculating
                        else "La liquidación está aprobada o cerrada; registre el cambio mediante un ajuste."
                    ),
                    value=row.periodo,
                )
            )
            continue

        novelty = PayrollNovelty(
            organization_id=user.organization_id,
            employee_id=employee.id,
            company_id=resolved_company,
            period=row.periodo,
            code=row.tipo,
            kind=row.naturaleza or NOVELTY_KIND,
            quantity=row.cantidad,
            unit=None,
            amount=row.importe,
            description=row.observacion,
            source=NOVELTY_SOURCE,
            external_id=None,
        )
        try:
            with db.begin_nested():
                db.add(novelty)
                db.flush()
        except IntegrityError:
            skipped += 1
            result.errors.append(
                RowError(
                    row=row_number,
                    field=None,
                    code="conflicto_bd",
                    message=(
                        "La novedad entra en conflicto con una clave unica "
                        "existente; la fila se omite."
                    ),
                    value=row.legajo,
                )
            )
            continue

        existing.add(key)
        _invalidate_runs(db, user, runs, "novelty_import")
        created += 1

    commit_or_conflict(db)
    return _serialize(
        result,
        created=created,
        skipped=skipped,
        company_id=company_id,
        source=NOVELTY_SOURCE,
    )


@router.post("/novelties/{novelty_id}/repair")
def repair_novelty_company(
    novelty_id: int, payload: RepairNoveltyInput, db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
) -> dict[str, Any]:
    """Assign an ambiguous legacy novelty without altering approved snapshots."""
    novelty = db.scalar(select(PayrollNovelty).join(Employee).where(
        PayrollNovelty.id == novelty_id,
        PayrollNovelty.organization_id == user.organization_id,
        Employee.organization_id == user.organization_id,
    ))
    if novelty is None:
        raise HTTPException(status_code=404, detail="Novedad no encontrada")
    year, month = int(novelty.period[:4]), int(novelty.period[4:])
    month_start = date(year, month, 1)
    next_month = date(year + (month == 12), month % 12 + 1, 1)
    companies = set(db.scalars(select(EmploymentContract.company_id).join(Company).where(
        EmploymentContract.employee_id == novelty.employee_id,
        Company.organization_id == user.organization_id,
        EmploymentContract.valid_from < next_month,
        or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= month_start),
    )))
    if payload.company_id not in companies:
        raise HTTPException(status_code=422, detail="La empresa debe pertenecer a la organización y tener contrato en el mes")

    # A NULL legacy novelty could have affected any contractual company.
    for company_id in sorted(companies):
        db.scalar(select(Company).where(Company.id == company_id).with_for_update())
        db.execute(update(Company).where(Company.id == company_id).values(active=Company.active))
    db.refresh(novelty)
    if novelty.company_id is not None:
        raise HTTPException(status_code=409, detail="La novedad ya tiene empresa asignada")
    runs = db.scalars(select(PayrollRun).where(
        PayrollRun.organization_id == user.organization_id,
        PayrollRun.company_id.in_(companies),
        PayrollRun.period_end >= month_start, PayrollRun.period_end < next_month,
    ).order_by(PayrollRun.id).with_for_update()).all()
    for run in runs:
        db.execute(update(PayrollRun).where(PayrollRun.id == run.id).values(status=PayrollRun.status))
        db.refresh(run)
    if any(run.status in {"APPROVED", "CLOSED", "VALIDATING"} for run in runs):
        raise HTTPException(status_code=409, detail="Hay liquidaciones aprobadas, cerradas o en cálculo para el mes")
    collision = db.scalar(select(PayrollNovelty.id).where(
        PayrollNovelty.id != novelty.id, PayrollNovelty.employee_id == novelty.employee_id,
        PayrollNovelty.company_id == payload.company_id, PayrollNovelty.period == novelty.period,
        PayrollNovelty.code == novelty.code, PayrollNovelty.source == novelty.source,
    ))
    if collision is not None:
        raise HTTPException(status_code=409, detail="Ya existe una novedad con la misma clave en la empresa")
    novelty.company_id = payload.company_id
    _invalidate_runs(db, user, runs, "novelty_company_repair")
    db.add(AuditLog(
        organization_id=user.organization_id, user_id=user.id, action="payroll_novelty.company_repaired",
        entity_type="PayrollNovelty", entity_id=str(novelty.id),
        before={"company_id": None}, after={"company_id": payload.company_id, "reason": payload.reason},
    ))
    commit_or_conflict(db)
    return {"id": novelty.id, "company_id": payload.company_id}


@router.post(
    "/employees",
    description=(
        "Importa empleados (HTTP 200 con valid_rows/errors[]/duplicates[]/warnings[]; "
        "no 422 por fila. CUIL: 11 digitos p. ej. 20-12345678-6; "
        "cabecera valida: Legajo;Apellido;Nombre;CUIL;Fecha de ingreso)."
    ),
)
def import_employees(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    company_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Importa empleados desde un CSV/XLSX.

    Con ``dry_run=true`` (por defecto) devuelve solo el preview. Con
    ``dry_run=false`` crea los empleados validos y devuelve el resultado del
    commit junto con los conteos de creados y omitidos. Los errores de fila y
    los duplicados no interrumpen el resto del lote. ``company_id`` es opcional
    y solo se usa para crear contratos minimos de los empleados nuevos.

    Contrato B-47P: siempre HTTP 200 con ``errors[]`` por fila (incluye
    ``cuil_invalido`` con formato 11 digitos y ``columna_faltante`` con
    cabecera valida); ``<``/``>`` se rechazan (V2-13) y ``= + - @``
    avisan ``formula_riesgosa`` (V2-12).
    """
    if not dry_run:
        _ensure_commit_role(user)

    content, filename = _read_upload(file)
    preview = _analyze(content, filename, "employees")
    if dry_run:
        return _serialize(preview)
    return _commit_employees(db, user, preview, company_id)


@router.post(
    "/novelties",
    description=(
        "Importa novedades (HTTP 200 con valid_rows/errors[]/duplicates[]/warnings[]; "
        "no 422 por fila. Cabecera valida: "
        "Legajo;Periodo;Tipo;Cantidad;Importe;Observacion)."
    ),
)
def import_novelties(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    company_id: int | None = Query(default=None, ge=1),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Analiza o persiste novedades desde un CSV/XLSX.

    Con ``dry_run=true`` (por defecto) devuelve solo el preview. Con
    ``dry_run=false`` persiste las filas validas en ``payroll_novelties`` y
    devuelve el resultado del commit junto con los conteos de creadas y
    omitidas. Las novedades ya importadas se informan como duplicadas y no
    interrumpen el resto del lote. ``company_id`` es opcional: si se informa,
    se valida que la empresa pertenezca a la organizacion y tenga contrato en
    el mes; si se omite debe haber una sola empresa contractual. Los duplicados
    no modifican liquidaciones. Nuevas filas reabren liquidaciones calculadas,
    y se rechazan si hay una aprobada, cerrada o en cálculo.

    Contrato B-47P: siempre HTTP 200 con ``errors[]`` por fila; ``<``/``>``
    en observacion/legajo se rechazan (V2-13).
    """
    if not dry_run:
        _ensure_commit_role(user)

    content, filename = _read_upload(file)
    preview = _analyze(content, filename, "novelties")
    if dry_run:
        return _serialize(preview)
    return _commit_novelties(db, user, preview, company_id)


@router.post(
    "/concepts",
    description=(
        "Importa conceptos (HTTP 200 con valid_rows/errors[]/duplicates[]/warnings[]; "
        "no 422 por fila. Cabecera valida: "
        "Codigo;Nombre;Naturaleza;Descripcion. Naturaleza: remunerativo, "
        "no remunerativo, descuento, contribucion o auxiliar)."
    ),
)
def import_concepts(
    file: UploadFile = File(...),
    dry_run: bool = Query(default=True),
    db: Session = Depends(get_db),
    user: User = Depends(require_user),
) -> dict[str, Any]:
    """Analiza o persiste conceptos desde un CSV/XLSX.

    Con ``dry_run=true`` (por defecto) devuelve solo el preview. Con
    ``dry_run=false`` crea los conceptos validos y devuelve el resultado del
    commit junto con los conteos de creados y omitidos. Los codigos ya
    existentes se informan como duplicados y no interrumpen el resto del lote.
    """

    if not dry_run:
        _ensure_commit_role(user)

    content, filename = _read_upload(file)
    preview = _analyze(content, filename, "concepts")
    if dry_run:
        return _serialize(preview)
    return _commit_concepts(db, user, preview)


__all__ = ["MAX_IMPORT_BYTES", "router"]
