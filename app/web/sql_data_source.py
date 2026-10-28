"""Web projections backed by the payroll SQLAlchemy models.

Every projection is scoped to one organization.  The source is created by the
application without an organization because the organization belongs to the
authenticated request, not to the process; :meth:`SqlAlchemyDataSource.for_organization`
returns a request-scoped copy that filters every query.  A source without an
organization deliberately returns no rows so a missed scope can never expose
cross-organization data.  The only write is the supervised review status of an
AI proposal, always restricted to the same organization.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from fastapi import HTTPException
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    SalaryScale,
    User,
)
from app.database.models import (
    AiProposal as PersistedProposal,
)
from app.database.session import SessionLocal
from app.web.demo_data import (
    Agreement as WebAgreement,
)
from app.web.demo_data import (
    AIProposal,
    PayrollEmployeeResult,
)
from app.web.demo_data import (
    Company as WebCompany,
)
from app.web.demo_data import (
    Employee as WebEmployee,
)
from app.web.demo_data import (
    PayrollConcept as WebPayrollConcept,
)
from app.web.demo_data import (
    PayrollRun as WebPayrollRun,
)
from app.web.demo_data import (
    Receipt as WebReceipt,
)

_ZERO = Decimal("0.00")
_MONTHS = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
_NATURES = {
    "REMUNERATIVE": "remunerative",
    "NON_REMUNERATIVE": "non_remunerative",
    "DEDUCTION": "deduction",
    "CONTRIBUTION": "contribution",
    "AUXILIARY": "auxiliary",
}
_RUN_STATUSES = {
    "DRAFT": "draft",
    "VALIDATING": "review",
    "CALCULATED": "calculated",
    "IN_REVIEW": "review",
    "APPROVED": "approved",
    "CLOSED": "closed",
    "ERROR": "error",
}
_RUN_TYPES = {
    "MONTHLY": "Mensual",
    "BIWEEKLY": "Quincenal",
    "WEEKLY": "Semanal",
    "SAC": "SAC",
    "VACATION": "Vacaciones",
    "VACATIONS": "Vacaciones",
    "FINAL": "Final",
    "COMPLEMENTARY": "Complementaria",
    "SIMULATION": "Simulación",
}
_PROPOSAL_STATUSES = {
    "draft": "draft",
    "validated": "in_review",
    "in_review": "in_review",
    "approved": "approved",
    "published": "approved",
    "rejected": "rejected",
}
_PROPOSAL_STATUS_FILTERS: dict[str, tuple[str, ...]] = {
    "draft": ("draft",),
    "in_review": ("validated", "in_review"),
    "validated": ("validated", "in_review"),
    "approved": ("approved", "published"),
    "published": ("published",),
    "rejected": ("rejected",),
}
_PROPOSAL_STATUS_DB = {
    "draft": "draft",
    "in_review": "validated",
    "approved": "approved",
    "rejected": "rejected",
}


def _proposal_status(value: str | None) -> str:
    return _PROPOSAL_STATUSES.get((value or "").casefold(), (value or "").casefold())


def _json_object(value: Any) -> dict[str, Any]:
    """Return a JSON object from a dict or a JSON-encoded string."""

    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _text_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _validation_warnings(value: Any) -> list[str]:
    warnings: list[str] = []
    reports = value if isinstance(value, list) else _json_object(value).get("reports")
    if not isinstance(reports, list):
        return warnings
    for report in reports:
        if not isinstance(report, dict):
            continue
        for key in ("errors", "warnings"):
            issues = report.get(key)
            if not isinstance(issues, list):
                continue
            for issue in issues:
                if isinstance(issue, dict) and str(issue.get("message") or "").strip():
                    warnings.append(str(issue["message"]).strip())
    return warnings


def _validation_is_valid(value: Any) -> bool:
    return _json_object(value).get("is_valid") is True


def _proposal_rules(raw: dict[str, Any]) -> list[str]:
    rules: list[str] = []
    formulas = raw.get("formulas")
    if isinstance(formulas, list):
        for formula in formulas:
            if not isinstance(formula, dict):
                continue
            label = str(formula.get("description") or formula.get("code") or "").strip()
            if label:
                rules.append(label)
    return rules


def _proposal_source(raw: dict[str, Any]) -> str:
    for key in ("formulas", "concepts", "parameters"):
        items = raw.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            source = item.get("source")
            if not isinstance(source, dict):
                continue
            article = str(source.get("article") or "").strip()
            page = source.get("page")
            if article and page is not None:
                return f"{article}, página {page}"
            if article:
                return article
            if page is not None:
                return f"Página {page}"
    return ""


def _id(value: str | int) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _matches(query: str, *values: Any) -> bool:
    needle = query.strip().casefold()
    return not needle or any(needle in str(value or "").casefold() for value in values)


def _like_pattern(query: str) -> str:
    """Patrón LIKE literal para búsqueda por texto (B-53/K-05)."""

    cleaned = query.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{cleaned}%"


def _use_sql_text_search(query: str) -> bool:
    """Indica si el texto libre puede filtrarse en SQL (B-53/K-05).

    SQLite aplica ``LIKE``/``ILIKE`` case-insensitive solo en ASCII; para
    no perder resultados con mayúsculas no-ASCII (p. ej. ``Ú`` vs ``ú``),
    esas búsquedas usan el filtro Python histórico con recall exacto.
    """

    return bool(query.strip()) and query.strip().isascii()


def _employee_text_filter(query: str, organization_id: int):
    """Filtro ILIKE por nombre/CUIL/legajo/categoría/empresa en SQL."""

    pattern = _like_pattern(query)
    full_name = Employee.first_name + " " + Employee.last_name
    company_match = (
        select(EmploymentContract.id)
        .join(Company, Company.id == EmploymentContract.company_id)
        .where(
            EmploymentContract.employee_id == Employee.id,
            Company.organization_id == organization_id,
            Company.legal_name.ilike(pattern, escape="\\"),
        )
        .exists()
    )
    category_match = (
        select(EmploymentContract.id)
        .join(AgreementCategory, AgreementCategory.id == EmploymentContract.category_id)
        .where(
            EmploymentContract.employee_id == Employee.id,
            AgreementCategory.name.ilike(pattern, escape="\\"),
        )
        .exists()
    )
    return or_(
        Employee.first_name.ilike(pattern, escape="\\"),
        Employee.last_name.ilike(pattern, escape="\\"),
        full_name.ilike(pattern, escape="\\"),
        Employee.cuil.ilike(pattern, escape="\\"),
        Employee.employee_code.ilike(pattern, escape="\\"),
        company_match,
        category_match,
    )


def _receipt_text_filter(query: str):
    """Filtra los mismos campos que muestra la búsqueda de recibos."""

    pattern = _like_pattern(query)
    full_name = Employee.first_name + " " + Employee.last_name
    number = (
        "R-" + func.substr(cast(PayrollRun.period_start, String), 1, 7)
        + "-" + PayrollRun.code + "-" + Employee.employee_code
    )
    return or_(
        number.ilike(pattern, escape="\\"),
        full_name.ilike(pattern, escape="\\"),
        cast(Employee.id, String).ilike(pattern, escape="\\"),
    )


def _status(value: str | None) -> str:
    return _RUN_STATUSES.get((value or "").upper(), (value or "").casefold())


def _period(value: date) -> str:
    return value.strftime("%Y-%m")


def _period_label(value: date) -> str:
    return f"{_MONTHS[value.month - 1].capitalize()} {value.year}"


def _location(address: str | None) -> tuple[str, str]:
    parts = [part.strip() for part in (address or "").split(",") if part.strip()]
    if len(parts) > 1:
        return ", ".join(parts[:-1]), parts[-1]
    return (parts[0], "") if parts else ("", "")


class SqlAlchemyDataSource:
    """The read-only SQL equivalent of :class:`DemoDataStore`.

    The current schema has no company address parts or agreement document links,
    so those views use the available fields and leave unsupported document
    counts empty.  ``ai_proposals`` is a persisted table and is projected from
    the raw JSON captured by the supervised AI pipeline.
    """

    is_demo = False
    source_name = "Base de datos SQL"
    explanation = (
        "La interfaz consulta la base SQL con el alcance de la organización del "
        "usuario autenticado. Empresas, empleados, convenios, liquidaciones, "
        "recibos, métricas y propuestas IA se filtran por organización; las "
        "propuestas se leen de ai_proposals y requieren revisión humana. La "
        "dirección se usa como ubicación porque la empresa no tiene campos "
        "separados de ciudad y provincia."
    )

    def __init__(
        self,
        session_factory: Callable[[], Session] = SessionLocal,
        organization_id: int | None = None,
    ) -> None:
        self._session_factory = session_factory
        self.organization_id = organization_id

    def for_organization(self, organization_id: int) -> SqlAlchemyDataSource:
        """Return a view of this source restricted to one organization."""

        return SqlAlchemyDataSource(self._session_factory, organization_id)

    def _scope(self) -> int | None:
        return self.organization_id

    def _companies(self, session: Session, rows: Sequence[Company]) -> list[WebCompany]:
        organization_id = self._scope()
        if not rows or organization_id is None:
            return []
        company_ids = [row.id for row in rows]
        today = date.today()
        contracts = session.execute(
            select(EmploymentContract, CollectiveAgreement, Employee)
            .join(Employee, Employee.id == EmploymentContract.employee_id)
            .outerjoin(CollectiveAgreement, CollectiveAgreement.id == EmploymentContract.agreement_id)
            .where(
                EmploymentContract.company_id.in_(company_ids),
                Employee.organization_id == organization_id,
            )
            .order_by(EmploymentContract.valid_from.desc())
        ).all()
        contracts_by_company: dict[int, list[tuple[EmploymentContract, CollectiveAgreement | None, Employee]]] = defaultdict(list)
        for contract, agreement_row, employee in contracts:
            contracts_by_company[contract.company_id].append((contract, agreement_row, employee))

        output = []
        for row in rows:
            candidates = contracts_by_company[row.id]
            current = [
                entry for entry in candidates
                if entry[0].active
                and entry[0].valid_from <= today
                and (entry[0].valid_to is None or entry[0].valid_to >= today)
            ]
            employee_ids = {
                contract.employee_id
                for contract, _agreement, employee in current
                if employee.active and (employee.termination_date is None or employee.termination_date >= today)
            }
            preferred = current or candidates
            agreement: CollectiveAgreement | None = preferred[0][1] if preferred else None
            city, province = _location(row.address)
            output.append(WebCompany(
                id=str(row.id),
                name=row.legal_name,
                cuit=row.cuit,
                city=city,
                province=province,
                activity=row.tax_activity or "",
                agreement=f"CCT {agreement.code}" if agreement else "",
                employee_count=len(employee_ids),
                status="active" if row.active else "inactive",
            ))
        return output

    def list_companies(self, query: str = "") -> list[WebCompany]:
        organization_id = self._scope()
        if organization_id is None:
            return []
        with self._session_factory() as session:
            statement = (
                select(Company)
                .where(Company.organization_id == organization_id)
                .order_by(Company.legal_name)
            )
            if _use_sql_text_search(query):
                # B-53/K-05: texto libre en SQL (razón social, CUIT,
                # domicilio o actividad) en vez de full-scan en Python.
                pattern = _like_pattern(query)
                statement = statement.where(
                    or_(
                        Company.legal_name.ilike(pattern, escape="\\"),
                        Company.cuit.ilike(pattern, escape="\\"),
                        Company.address.ilike(pattern, escape="\\"),
                        Company.tax_activity.ilike(pattern, escape="\\"),
                    )
                )
            rows = session.scalars(statement).all()
            return [
                company for company in self._companies(session, rows)
                if _matches(query, company.name, company.cuit, company.city, company.activity)
            ]

    def get_company(self, company_id: str) -> WebCompany | None:
        row_id = _id(company_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(Company, row_id)
            if row is None or row.organization_id != organization_id:
                return None
            return self._companies(session, [row])[0]

    def _employees(
        self,
        session: Session,
        rows: Sequence[Employee],
        preferred_company_id: int | None = None,
    ) -> list[WebEmployee]:
        organization_id = self._scope()
        if not rows or organization_id is None:
            return []
        employee_ids = [row.id for row in rows]
        today = date.today()
        company_ids_subquery = select(Company.id).where(Company.organization_id == organization_id)
        contract_rows = session.execute(
            select(EmploymentContract, AgreementCategory, CollectiveAgreement)
            .outerjoin(AgreementCategory, AgreementCategory.id == EmploymentContract.category_id)
            .outerjoin(CollectiveAgreement, CollectiveAgreement.id == EmploymentContract.agreement_id)
            .where(
                EmploymentContract.employee_id.in_(employee_ids),
                EmploymentContract.company_id.in_(company_ids_subquery),
            )
            .order_by(EmploymentContract.valid_from.desc())
        ).all()
        contracts_by_employee: dict[int, list[tuple[EmploymentContract, AgreementCategory | None, CollectiveAgreement | None]]] = defaultdict(list)
        for contract_row, category_row, agreement_row in contract_rows:
            contracts_by_employee[contract_row.employee_id].append(
                (contract_row, category_row, agreement_row)
            )
        company_ids = {contract.company_id for contract, _category, _agreement in contract_rows}
        companies = {
            company.id: company
            for company in session.scalars(
                select(Company).where(
                    Company.id.in_(company_ids),
                    Company.organization_id == organization_id,
                )
            ).all()
        } if company_ids else {}
        category_ids = {category.id for _contract, category, _agreement in contract_rows if category}
        scales_by_category: dict[int, list[SalaryScale]] = defaultdict(list)
        if category_ids:
            for salary_scale in session.scalars(
                select(SalaryScale)
                .where(SalaryScale.category_id.in_(category_ids), SalaryScale.valid_from <= today)
                .order_by(SalaryScale.valid_from.desc())
            ).all():
                if salary_scale.valid_to is None or salary_scale.valid_to >= today:
                    scales_by_category[salary_scale.category_id].append(salary_scale)

        output = []
        for employee in rows:
            candidates = contracts_by_employee[employee.id]
            current = [
                entry for entry in candidates
                if entry[0].active
                and entry[0].valid_from <= today
                and (entry[0].valid_to is None or entry[0].valid_to >= today)
            ]
            if preferred_company_id is not None:
                current_for_company = [entry for entry in current if entry[0].company_id == preferred_company_id]
                candidates_for_company = [entry for entry in candidates if entry[0].company_id == preferred_company_id]
                selected = (current_for_company or candidates_for_company or current or candidates)
            else:
                selected = current or candidates
            contract: EmploymentContract | None
            category: AgreementCategory | None
            agreement: CollectiveAgreement | None
            contract, category, agreement = selected[0] if selected else (None, None, None)
            company = companies.get(contract.company_id) if contract else None
            category_scales = scales_by_category.get(category.id, []) if category else []
            scale = category_scales[0] if category_scales else None
            salary = (
                contract.monthly_salary
                if contract and contract.monthly_salary is not None
                else (scale.base_salary + scale.additional if scale else _ZERO)
            )
            active = employee.active and (
                employee.termination_date is None or employee.termination_date >= today
            )
            output.append(WebEmployee(
                id=str(employee.id),
                name=f"{employee.first_name} {employee.last_name}".strip(),
                cuil=employee.cuil or "",
                file_number=employee.employee_code,
                company_id=str(contract.company_id) if contract else "",
                company_name=company.legal_name if company else "",
                category=category.name if category else "",
                agreement=f"CCT {agreement.code}" if agreement else "",
                hire_date=employee.hire_date or (contract.valid_from if contract else today),
                salary=salary,
                status="active" if active else "inactive",
                email=employee.email or "",
                phone="",
            ))
        return output

    def employees_for_company(self, company_id: str) -> list[WebEmployee]:
        return self.list_employees(company_id=company_id)

    def list_employees(
        self,
        query: str = "",
        company_id: str = "",
        status: str = "",
        limit: int | None = None,
        offset: int = 0,
    ) -> list[WebEmployee]:
        requested_company = _id(company_id) if company_id else None
        organization_id = self._scope()
        if (company_id and requested_company is None) or organization_id is None:
            return []
        # Los filtros estructurados se aplican en SQL.
        today = date.today()
        wanted = status.casefold() if status else ""
        if wanted and wanted not in {"active", "inactive"}:
            return []
        with self._session_factory() as session:
            statement = (
                select(Employee)
                .where(Employee.organization_id == organization_id)
                .order_by(Employee.last_name, Employee.first_name)
            )
            if requested_company is not None:
                statement = statement.where(
                    select(EmploymentContract.id)
                    .join(Company, Company.id == EmploymentContract.company_id)
                    .where(
                        EmploymentContract.employee_id == Employee.id,
                        EmploymentContract.company_id == requested_company,
                        Company.organization_id == organization_id,
                    )
                    .exists()
                )
            if wanted == "active":
                statement = statement.where(
                    Employee.active.is_(True),
                    or_(Employee.termination_date.is_(None), Employee.termination_date >= today),
                )
            elif wanted == "inactive":
                statement = statement.where(
                    or_(
                        Employee.active.is_not(True),
                        Employee.termination_date < today,
                    )
                )
            if _use_sql_text_search(query):
                statement = statement.where(_employee_text_filter(query, organization_id))
            if query.strip():
                # El SQL incluye contratos históricos; filtrar los datos del
                # contrato mostrado antes de contar resultados para la página.
                matched: list[WebEmployee] = []
                batch_size = max(limit or 50, 50)
                batch_offset = 0
                while True:
                    rows = session.scalars(statement.limit(batch_size).offset(batch_offset)).all()
                    matched.extend(
                        employee for employee in self._employees(session, rows, requested_company)
                        if _matches(
                            query, employee.name, employee.cuil, employee.file_number,
                            employee.category, employee.company_name,
                        )
                    )
                    if len(rows) < batch_size or (limit is not None and len(matched) >= offset + limit):
                        break
                    batch_offset += batch_size
                return matched if limit is None else matched[offset:offset + limit]
            if limit is not None:
                statement = statement.limit(limit).offset(offset)
            rows = session.scalars(statement).all()
            employees = self._employees(session, rows, requested_company)
            # Refinamiento en Python con la misma semántica histórica.
            return [
                employee for employee in employees
                if _matches(
                    query,
                    employee.name,
                    employee.cuil,
                    employee.file_number,
                    employee.category,
                    employee.company_name,
                )
            ]

    def get_employee(self, employee_id: str) -> WebEmployee | None:
        row_id = _id(employee_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(Employee, row_id)
            if row is None or row.organization_id != organization_id:
                return None
            return self._employees(session, [row])[0]

    def _agreements(self, session: Session, rows: Sequence[CollectiveAgreement]) -> list[WebAgreement]:
        if not rows:
            return []
        agreement_ids = [row.id for row in rows]
        categories = session.scalars(
            select(AgreementCategory)
            .where(AgreementCategory.agreement_id.in_(agreement_ids))
            .order_by(AgreementCategory.name)
        ).all()
        names: dict[int, list[str]] = defaultdict(list)
        category_ids: set[int] = set()
        for category in categories:
            names[category.agreement_id].append(category.name)
            category_ids.add(category.id)
        scales = session.scalars(
            select(SalaryScale)
            .where(SalaryScale.category_id.in_(category_ids))
            .order_by(SalaryScale.valid_from)
        ).all() if category_ids else []
        starts: dict[int, list[date]] = defaultdict(list)
        category_to_agreement = {category.id: category.agreement_id for category in categories}
        for scale in scales:
            starts[category_to_agreement[scale.category_id]].append(scale.valid_from)
        return [WebAgreement(
            id=str(row.id),
            code=f"CCT {row.code}",
            name=row.name,
            scope=row.scope or "",
            categories=names[row.id],
            valid_from=min(starts[row.id]) if starts[row.id] else date.today(),
            status="active" if row.active else "inactive",
            formula_count=0,
            document_count=0,
            summary=row.scope or "Convenio registrado en la base de datos.",
        ) for row in rows]

    def _agreement_ids(self, session: Session, organization_id: int) -> set[int]:
        """Agreements are global, so scope them through the organization's contracts."""

        return {
            agreement_id
            for agreement_id in session.scalars(
                select(EmploymentContract.agreement_id)
                .join(Employee, Employee.id == EmploymentContract.employee_id)
                .join(Company, Company.id == EmploymentContract.company_id)
                .where(
                    Employee.organization_id == organization_id,
                    Company.organization_id == organization_id,
                    EmploymentContract.agreement_id.is_not(None),
                )
            ).all()
            if agreement_id is not None
        }

    def list_agreements(self, query: str = "") -> list[WebAgreement]:
        organization_id = self._scope()
        if organization_id is None:
            return []
        with self._session_factory() as session:
            agreement_ids = self._agreement_ids(session, organization_id)
            if not agreement_ids:
                return []
            rows = session.scalars(
                select(CollectiveAgreement)
                .where(CollectiveAgreement.id.in_(agreement_ids))
                .order_by(CollectiveAgreement.code, CollectiveAgreement.year)
            ).all()
            return [
                agreement for agreement in self._agreements(session, rows)
                if _matches(query, agreement.code, agreement.name, agreement.scope)
            ]

    def get_agreement(self, agreement_id: str) -> WebAgreement | None:
        row_id = _id(agreement_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(CollectiveAgreement, row_id)
            if row is None or row.id not in self._agreement_ids(session, organization_id):
                return None
            return self._agreements(session, [row])[0]

    def _payrolls(self, session: Session, rows: Sequence[PayrollRun]) -> list[WebPayrollRun]:
        organization_id = self._scope()
        if not rows or organization_id is None:
            return []
        run_ids = [row.id for row in rows]
        company_ids = {row.company_id for row in rows}
        companies = {
            company.id: company
            for company in session.scalars(
                select(Company).where(
                    Company.id.in_(company_ids),
                    Company.organization_id == organization_id,
                )
            ).all()
        }
        results = session.scalars(
            select(PayrollResult)
            .where(PayrollResult.payroll_run_id.in_(run_ids))
            .order_by(PayrollResult.id)
        ).all()
        results_by_run: dict[int, list[PayrollResult]] = defaultdict(list)
        for result in results:
            results_by_run[result.payroll_run_id].append(result)
        result_ids = [result.id for result in results]
        employees = {
            employee.id: employee
            for employee in session.scalars(
                select(Employee).where(
                    Employee.id.in_({result.employee_id for result in results}),
                    Employee.organization_id == organization_id,
                )
            ).all()
        } if results else {}
        items_by_result: dict[int, list[PayrollItem]] = defaultdict(list)
        if result_ids:
            for item in session.scalars(
                select(PayrollItem).where(PayrollItem.payroll_result_id.in_(result_ids)).order_by(PayrollItem.id)
            ).all():
                items_by_result[item.payroll_result_id].append(item)

        output = []
        for row in rows:
            run_results = results_by_run[row.id]
            run_items = [item for result in run_results for item in items_by_result[result.id]]
            totals: dict[str, Decimal] = defaultdict(lambda: _ZERO)
            quantities: dict[str, Decimal] = defaultdict(lambda: _ZERO)
            counts: dict[str, int] = defaultdict(int)
            names: dict[str, str] = {}
            kinds: dict[str, str] = {}
            for item in run_items:
                totals[item.code] += item.amount
                quantities[item.code] += item.quantity or _ZERO
                counts[item.code] += 1
                names[item.code] = item.description
                kinds[item.code] = _NATURES.get(item.nature, item.nature.casefold())
            concepts = [WebPayrollConcept(
                code=code,
                name=names[code],
                kind=kinds[code],
                amount=totals[code],
                quantity=quantities[code] or Decimal(counts[code]),
            ) for code in sorted(totals)]
            employee_results = []
            for result in run_results:
                employee = employees.get(result.employee_id)
                employee_results.append(PayrollEmployeeResult(
                    employee_id=str(result.employee_id),
                    employee_name=(f"{employee.first_name} {employee.last_name}".strip() if employee else ""),
                    cuil=employee.cuil or "" if employee else "",
                    gross=result.gross,
                    deductions=result.deductions,
                    net=result.net,
                ))
            created_at = row.created_at.date() if isinstance(row.created_at, datetime) else row.period_end
            output.append(WebPayrollRun(
                id=str(row.id),
                company_id=str(row.company_id),
                company_name=companies[row.company_id].legal_name if row.company_id in companies else "",
                period=_period(row.period_start),
                period_label=_period_label(row.period_start),
                type=_RUN_TYPES.get(row.run_type.upper(), row.run_type.replace("_", " ").title()),
                status=_status(row.status),
                employee_count=len(run_results),
                gross=sum((result.gross for result in run_results), _ZERO),
                deductions=sum((result.deductions for result in run_results), _ZERO),
                net=sum((result.net for result in run_results), _ZERO),
                employer_cost=sum((result.employer_cost for result in run_results), _ZERO),
                created_at=created_at,
                concepts=concepts,
                employee_results=employee_results,
            ))
        return output

    def list_payrolls(self, status: str = "", company_id: str = "") -> list[WebPayrollRun]:
        requested_company = _id(company_id) if company_id else None
        organization_id = self._scope()
        if (company_id and requested_company is None) or organization_id is None:
            return []
        with self._session_factory() as session:
            statement = (
                select(PayrollRun)
                .where(PayrollRun.organization_id == organization_id)
                .order_by(PayrollRun.period_start.desc(), PayrollRun.id.desc())
            )
            if requested_company is not None:
                statement = statement.where(PayrollRun.company_id == requested_company)
            rows = session.scalars(statement).all()
            payrolls = self._payrolls(session, rows)
            return [payroll for payroll in payrolls if not status or payroll.status == status.casefold()]

    def get_payroll(self, payroll_id: str) -> WebPayrollRun | None:
        row_id = _id(payroll_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(PayrollRun, row_id)
            if row is None or row.organization_id != organization_id:
                return None
            return self._payrolls(session, [row])[0]

    def _proposal(self, row: PersistedProposal) -> AIProposal:
        raw = _json_object(row.raw_json)
        number = str(raw.get("agreement_number") or "").strip()
        agreement_title = str(raw.get("agreement_title") or "").strip()
        if number:
            agreement = number if number.upper().startswith("CCT") else f"CCT {number}"
        else:
            agreement = agreement_title
        title = (row.title or agreement_title).strip() if (row.title or agreement_title) else ""
        validation = row.validation_json
        warnings = _text_items(raw.get("ambiguities")) + _text_items(raw.get("security_warnings"))
        warnings.extend(_validation_warnings(validation))
        created_at = (
            row.created_at.date() if isinstance(row.created_at, datetime) else date.today()
        )
        return AIProposal(
            id=str(row.id),
            title=title or f"Propuesta {row.id}",
            agreement=agreement,
            document=row.document_id,
            status=_proposal_status(row.status),
            confidence=Decimal("100.0") if _validation_is_valid(validation) else Decimal("0.0"),
            created_at=created_at,
            summary=str(raw.get("summary") or "").strip()
            or "Propuesta persistida en la base de datos, pendiente de revisión humana.",
            rules=_proposal_rules(raw),
            warnings=warnings,
            source_page=_proposal_source(raw),
        )

    def list_proposals(self, status: str = "") -> list[AIProposal]:
        organization_id = self._scope()
        if organization_id is None:
            return []
        if status and status.casefold() not in _PROPOSAL_STATUS_FILTERS:
            return []
        with self._session_factory() as session:
            statement = (
                select(PersistedProposal)
                .where(PersistedProposal.organization_id == organization_id)
                .order_by(PersistedProposal.created_at.desc(), PersistedProposal.id.desc())
            )
            if status:
                statement = statement.where(
                    PersistedProposal.status.in_(_PROPOSAL_STATUS_FILTERS[status.casefold()])
                )
            rows = session.scalars(statement).all()
            return [self._proposal(row) for row in rows]

    def get_proposal(self, proposal_id: str) -> AIProposal | None:
        row_id = _id(proposal_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(PersistedProposal, row_id)
            if row is None or row.organization_id != organization_id:
                return None
            return self._proposal(row)

    def set_proposal_status(self, proposal_id: str, status: str, *, user_id: int | None = None) -> AIProposal | None:
        if status not in _PROPOSAL_STATUS_DB:
            raise ValueError(f"Estado de propuesta no valido: {status}")
        row_id = _id(proposal_id)
        organization_id = self._scope()
        if row_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(PersistedProposal, row_id)
            if row is None or row.organization_id != organization_id:
                return None
            user = session.get(User, user_id) if user_id is not None else None
            if user is None or not user.active or user.organization_id != organization_id or user.role not in {"admin", "editor"}:
                raise HTTPException(status_code=403, detail="Permiso insuficiente.")
            if row.status not in {"draft", "validated"}:
                raise HTTPException(status_code=409, detail="La propuesta ya fue revisada o publicada.")
            if status == "approved":
                from app.api.ai import approve_persisted_ai_proposal

                row = approve_persisted_ai_proposal(row_id, session, user)
                return self._proposal(row)
            if status == "in_review":
                from app.api.ai import (
                    _analysis_from_proposal,
                    _ensure_valid_reports,
                    _reports_for_analysis,
                    _stored_validation_is_valid,
                )

                if not _stored_validation_is_valid(row.validation_json):
                    raise HTTPException(status_code=409, detail="La propuesta no tiene una validación determinística satisfactoria")
                _ensure_valid_reports(_reports_for_analysis(_analysis_from_proposal(row)))
            row.status = _PROPOSAL_STATUS_DB[status]
            session.commit()
            session.refresh(row)
            return self._proposal(row)

    def _receipts(
        self,
        session: Session,
        result_rows: Sequence[Row[PayrollResult, PayrollRun]],
    ) -> list[WebReceipt]:
        organization_id = self._scope()
        if not result_rows or organization_id is None:
            return []
        run_rows = list({run.id: run for _result, run in result_rows}.values())
        payrolls = {payroll.id: payroll for payroll in self._payrolls(session, run_rows)}
        result_ids = [result.id for result, _run in result_rows]
        items_by_result: dict[int, list[PayrollItem]] = defaultdict(list)
        for item in session.scalars(
            select(PayrollItem).where(PayrollItem.payroll_result_id.in_(result_ids)).order_by(PayrollItem.id)
        ).all():
            items_by_result[item.payroll_result_id].append(item)
        employee_ids = {result.employee_id for result, _run in result_rows}
        employees = {
            employee.id: employee
            for employee in session.scalars(
                select(Employee).where(
                    Employee.id.in_(employee_ids),
                    Employee.organization_id == organization_id,
                )
            ).all()
        }
        employee_views = {
            int(employee.id): employee
            for employee in self._employees(session, list(employees.values()))
        }
        companies = {
            company.id: company
            for company in session.scalars(
                select(Company).where(
                    Company.id.in_({run.company_id for _result, run in result_rows}),
                    Company.organization_id == organization_id,
                )
            ).all()
        }
        output = []
        for result, run in result_rows:
            payroll = payrolls[str(run.id)]
            employee = employees.get(result.employee_id)
            employee_view = employee_views.get(result.employee_id)
            company = companies.get(run.company_id)
            if employee is None or employee_view is None or company is None:
                continue
            items = [
                WebPayrollConcept(
                    code=item.code,
                    name=item.description,
                    kind=_NATURES[item.nature],
                    amount=item.amount,
                    quantity=item.quantity or Decimal("1"),
                )
                for item in items_by_result[result.id]
                if item.nature in _NATURES and item.nature != "AUXILIARY"
            ]
            issued_on = result.calculated_at.date() if result.calculated_at else run.period_end
            output.append(WebReceipt(
                id=str(result.id),
                payroll_id=str(run.id),
                number=f"R-{payroll.period}-{run.code}-{employee.employee_code}",
                company_id=str(company.id),
                employee_id=str(employee.id),
                period=payroll.period,
                period_label=payroll.period_label,
                net=result.net,
                status="issued" if payroll.status in {"approved", "closed"} else "pending",
                issued_on=issued_on,
                employer={
                    "name": company.legal_name,
                    "cuit": company.cuit,
                    "address": company.address or "",
                    "activity": company.tax_activity or "",
                },
                employee={
                    "name": employee_view.name,
                    "cuil": employee.cuil or "",
                    "file_number": employee.employee_code,
                    "category": employee_view.category,
                    "hire_date": employee.hire_date,
                    "agreement": employee_view.agreement,
                },
                items=items,
                remunerative_total=result.remunerative,
                non_remunerative_total=result.non_remunerative,
                deductions_total=result.deductions,
                contributions_total=result.contributions,
            ))
        return output

    def list_receipts(
        self,
        query: str = "",
        company_id: str = "",
        period: str = "",
        status: str = "",
        limit: int | None = None,
        offset: int = 0,
        payroll_id: str = "",
    ) -> list[WebReceipt]:
        requested_company = _id(company_id) if company_id else None
        requested_payroll = _id(payroll_id) if payroll_id else None
        organization_id = self._scope()
        if (company_id and requested_company is None) or (payroll_id and requested_payroll is None) or organization_id is None:
            return []
        # B-53/K-05: filtros estructurados y texto libre en SQL (rango de mes
        # por período, sin funciones de dialecto); la paginación siempre se
        # aplica en SQL.
        wanted = status.casefold() if status else ""
        if wanted and wanted not in {"issued", "pending"}:
            return []
        month_start: date | None = None
        if period:
            try:
                year, month = (int(part) for part in period.split("-"))
                month_start = date(year, month, 1)
            except (TypeError, ValueError):
                return []
        with self._session_factory() as session:
            statement = (
                select(PayrollResult, PayrollRun)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .where(PayrollRun.organization_id == organization_id, PayrollRun.status != "ANNULLED")
                .order_by(PayrollRun.period_start.desc(), PayrollResult.id.desc())
            )
            if requested_company is not None:
                statement = statement.where(PayrollRun.company_id == requested_company)
            if requested_payroll is not None:
                statement = statement.where(PayrollRun.id == requested_payroll)
            if month_start is not None:
                statement = statement.where(PayrollRun.period_start >= month_start)
                if month_start != date(9999, 12, 1):
                    next_month = date(
                        month_start.year + (month_start.month == 12),
                        month_start.month % 12 + 1,
                        1,
                    )
                    statement = statement.where(PayrollRun.period_start < next_month)
            if wanted == "issued":
                statement = statement.where(func.upper(PayrollRun.status).in_(("APPROVED", "CLOSED")))
            elif wanted == "pending":
                statement = statement.where(func.upper(PayrollRun.status).not_in(("APPROVED", "CLOSED")))
            if _use_sql_text_search(query):
                statement = (
                    statement
                    .join(Employee, Employee.id == PayrollResult.employee_id)
                    .where(_receipt_text_filter(query))
                )
            elif query.strip():
                # Consulta no-ASCII: filtro y paginación en Python con recall
                # exacto (ver `_use_sql_text_search`).
                rows = session.execute(statement).all()
                matched = [
                    receipt for receipt in self._receipts(session, rows)
                    if _matches(query, receipt.number, receipt.employee.get("name"), receipt.employee_id)
                ]
                return matched if limit is None else matched[offset:offset + limit]
            if limit is not None:
                statement = statement.limit(limit).offset(offset)
            rows = session.execute(statement).all()
            receipts = self._receipts(session, rows)
            # Refinamiento en Python con la misma semántica histórica.
            return [
                receipt for receipt in receipts
                if _matches(query, receipt.number, receipt.employee.get("name"), receipt.employee_id)
            ]

    def get_receipt(self, receipt_id: str) -> WebReceipt | None:
        result_id = _id(receipt_id)
        organization_id = self._scope()
        if result_id is None or organization_id is None:
            return None
        with self._session_factory() as session:
            row = session.execute(
                select(PayrollResult, PayrollRun)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .where(
                    PayrollResult.id == result_id,
                    PayrollRun.organization_id == organization_id,
                    PayrollRun.status != "ANNULLED",
                )
            ).first()
            return self._receipts(session, [row])[0] if row else None

    def receipt_periods(self) -> list[tuple[str, str]]:
        # B-53/K-05: DISTINCT en SQL en vez de volcar todos los recibos.
        organization_id = self._scope()
        if organization_id is None:
            return []
        with self._session_factory() as session:
            starts = session.scalars(
                select(PayrollRun.period_start)
                .where(PayrollRun.organization_id == organization_id)
                .distinct()
                .order_by(PayrollRun.period_start.desc())
            ).all()
        return sorted(
            {(_period(start), _period_label(start)) for start in starts},
            reverse=True,
        )

    def dashboard_metrics(self) -> dict[str, Any]:
        today = date.today()
        organization_id = self._scope()
        if organization_id is None:
            return {
                "companies": 0,
                "active_employees": 0,
                "in_review": 0,
                "pending_proposals": 0,
                "issued_receipts": 0,
                "latest_payroll": None,
                "total_net": _ZERO,
                "total_gross": _ZERO,
                "employer_cost": _ZERO,
            }
        with self._session_factory() as session:
            companies_count = session.scalar(
                select(func.count())
                .select_from(Company)
                .where(Company.organization_id == organization_id)
            ) or 0
            active_employees = session.scalar(
                select(func.count(func.distinct(Employee.id)))
                .join(EmploymentContract, EmploymentContract.employee_id == Employee.id)
                .join(Company, Company.id == EmploymentContract.company_id)
                .where(
                    Employee.organization_id == organization_id,
                    Company.organization_id == organization_id,
                    Employee.active.is_(True),
                    or_(Employee.termination_date.is_(None), Employee.termination_date >= today),
                    EmploymentContract.active.is_(True),
                    EmploymentContract.valid_from <= today,
                    or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= today),
                )
            ) or 0
            rows = session.scalars(
                select(PayrollRun)
                .where(PayrollRun.organization_id == organization_id)
                .order_by(PayrollRun.period_start.desc(), PayrollRun.id.desc())
            ).all()
            payrolls = self._payrolls(session, rows)
            latest = next((payroll for payroll in payrolls if payroll.status != "draft"), payrolls[0] if payrolls else None)
            issued_receipts = session.scalar(
                select(func.count())
                .select_from(PayrollResult)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .where(
                    PayrollRun.organization_id == organization_id,
                    PayrollRun.status.in_(("APPROVED", "CLOSED")),
                )
            ) or 0
            pending_proposals = session.scalar(
                select(func.count())
                .select_from(PersistedProposal)
                .where(
                    PersistedProposal.organization_id == organization_id,
                    PersistedProposal.status.in_(("draft", "validated")),
                )
            ) or 0
            return {
                "companies": companies_count,
                "active_employees": active_employees,
                "in_review": sum(payroll.status in {"calculated", "review"} for payroll in payrolls),
                "pending_proposals": pending_proposals,
                "issued_receipts": issued_receipts,
                "latest_payroll": latest,
                "total_net": latest.net if latest else _ZERO,
                "total_gross": latest.gross if latest else _ZERO,
                "employer_cost": latest.employer_cost if latest else _ZERO,
            }


__all__ = ["SqlAlchemyDataSource"]
