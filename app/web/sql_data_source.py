"""Read-only web projections backed by the payroll SQLAlchemy models."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select
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
    "FINAL": "Final",
    "COMPLEMENTARY": "Complementaria",
    "SIMULATION": "Simulación",
}


def _id(value: str | int) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _matches(query: str, *values: Any) -> bool:
    needle = query.strip().casefold()
    return not needle or any(needle in str(value or "").casefold() for value in values)


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

    The current schema has no company address parts, agreement document links,
    or persisted AI proposal table, so those views use the available fields and
    leave unsupported proposal and document counts empty.
    """

    is_demo = False
    source_name = "Base de datos SQL"
    explanation = (
        "La interfaz consulta la base SQL. Las propuestas IA quedan vacías y los "
        "conteos de fórmulas y documentos por convenio son cero porque el esquema "
        "todavía no relaciona esos datos. La dirección se usa como ubicación porque "
        "la empresa no tiene campos separados de ciudad y provincia."
    )

    def __init__(self, session_factory: Callable[[], Session] = SessionLocal) -> None:
        self._session_factory = session_factory

    def _companies(self, session: Session, rows: Sequence[Company]) -> list[WebCompany]:
        if not rows:
            return []
        company_ids = [row.id for row in rows]
        today = date.today()
        contracts = session.execute(
            select(EmploymentContract, CollectiveAgreement, Employee)
            .join(Employee, Employee.id == EmploymentContract.employee_id)
            .outerjoin(CollectiveAgreement, CollectiveAgreement.id == EmploymentContract.agreement_id)
            .where(EmploymentContract.company_id.in_(company_ids))
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
        with self._session_factory() as session:
            rows = session.scalars(select(Company).order_by(Company.legal_name)).all()
            return [
                company for company in self._companies(session, rows)
                if _matches(query, company.name, company.cuit, company.city, company.activity)
            ]

    def get_company(self, company_id: str) -> WebCompany | None:
        row_id = _id(company_id)
        if row_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(Company, row_id)
            return self._companies(session, [row])[0] if row else None

    def _employees(
        self,
        session: Session,
        rows: Sequence[Employee],
        preferred_company_id: int | None = None,
    ) -> list[WebEmployee]:
        if not rows:
            return []
        employee_ids = [row.id for row in rows]
        today = date.today()
        contract_rows = session.execute(
            select(EmploymentContract, AgreementCategory, CollectiveAgreement)
            .outerjoin(AgreementCategory, AgreementCategory.id == EmploymentContract.category_id)
            .outerjoin(CollectiveAgreement, CollectiveAgreement.id == EmploymentContract.agreement_id)
            .where(EmploymentContract.employee_id.in_(employee_ids))
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
            for company in session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
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
    ) -> list[WebEmployee]:
        requested_company = _id(company_id) if company_id else None
        if company_id and requested_company is None:
            return []
        with self._session_factory() as session:
            rows = session.scalars(select(Employee).order_by(Employee.last_name, Employee.first_name)).all()
            employees = self._employees(session, rows, requested_company)
            return [
                employee for employee in employees
                if (not company_id or employee.company_id == company_id)
                and (not status or employee.status == status.casefold())
                and _matches(
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
        if row_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(Employee, row_id)
            return self._employees(session, [row])[0] if row else None

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

    def list_agreements(self, query: str = "") -> list[WebAgreement]:
        with self._session_factory() as session:
            rows = session.scalars(
                select(CollectiveAgreement).order_by(CollectiveAgreement.code, CollectiveAgreement.year)
            ).all()
            return [
                agreement for agreement in self._agreements(session, rows)
                if _matches(query, agreement.code, agreement.name, agreement.scope)
            ]

    def get_agreement(self, agreement_id: str) -> WebAgreement | None:
        row_id = _id(agreement_id)
        if row_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(CollectiveAgreement, row_id)
            return self._agreements(session, [row])[0] if row else None

    def _payrolls(self, session: Session, rows: Sequence[PayrollRun]) -> list[WebPayrollRun]:
        if not rows:
            return []
        run_ids = [row.id for row in rows]
        company_ids = {row.company_id for row in rows}
        companies = {
            company.id: company
            for company in session.scalars(select(Company).where(Company.id.in_(company_ids))).all()
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
                select(Employee).where(Employee.id.in_({result.employee_id for result in results}))
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
        if company_id and requested_company is None:
            return []
        with self._session_factory() as session:
            statement = select(PayrollRun).order_by(PayrollRun.period_start.desc(), PayrollRun.id.desc())
            if requested_company is not None:
                statement = statement.where(PayrollRun.company_id == requested_company)
            rows = session.scalars(statement).all()
            payrolls = self._payrolls(session, rows)
            return [payroll for payroll in payrolls if not status or payroll.status == status.casefold()]

    def get_payroll(self, payroll_id: str) -> WebPayrollRun | None:
        row_id = _id(payroll_id)
        if row_id is None:
            return None
        with self._session_factory() as session:
            row = session.get(PayrollRun, row_id)
            return self._payrolls(session, [row])[0] if row else None

    def list_proposals(self, status: str = "") -> list[AIProposal]:
        return []

    def get_proposal(self, proposal_id: str) -> AIProposal | None:
        return None

    def set_proposal_status(self, proposal_id: str, status: str) -> AIProposal | None:
        raise ValueError("No hay propuestas IA persistidas en la base de datos.")

    def _receipts(
        self,
        session: Session,
        result_rows: Sequence[Row[PayrollResult, PayrollRun]],
    ) -> list[WebReceipt]:
        if not result_rows:
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
            for employee in session.scalars(select(Employee).where(Employee.id.in_(employee_ids))).all()
        }
        employee_views = {
            int(employee.id): employee
            for employee in self._employees(session, list(employees.values()))
        }
        companies = {
            company.id: company
            for company in session.scalars(
                select(Company).where(Company.id.in_({run.company_id for _result, run in result_rows}))
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
    ) -> list[WebReceipt]:
        requested_company = _id(company_id) if company_id else None
        if company_id and requested_company is None:
            return []
        with self._session_factory() as session:
            statement = (
                select(PayrollResult, PayrollRun)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .order_by(PayrollRun.period_start.desc(), PayrollResult.id.desc())
            )
            if requested_company is not None:
                statement = statement.where(PayrollRun.company_id == requested_company)
            rows = session.execute(statement).all()
            receipts = self._receipts(session, rows)
            return [
                receipt for receipt in receipts
                if (not period or receipt.period == period)
                and (not status or receipt.status == status.casefold())
                and _matches(query, receipt.number, receipt.employee.get("name"), receipt.employee_id)
            ]

    def get_receipt(self, receipt_id: str) -> WebReceipt | None:
        result_id = _id(receipt_id)
        if result_id is None:
            return None
        with self._session_factory() as session:
            row = session.execute(
                select(PayrollResult, PayrollRun)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .where(PayrollResult.id == result_id)
            ).first()
            return self._receipts(session, [row])[0] if row else None

    def receipt_periods(self) -> list[tuple[str, str]]:
        receipts = self.list_receipts()
        return sorted({(receipt.period, receipt.period_label) for receipt in receipts}, reverse=True)

    def dashboard_metrics(self) -> dict[str, Any]:
        today = date.today()
        with self._session_factory() as session:
            companies_count = session.scalar(select(func.count()).select_from(Company)) or 0
            active_employees = session.scalar(
                select(func.count(func.distinct(Employee.id)))
                .join(EmploymentContract, EmploymentContract.employee_id == Employee.id)
                .where(
                    Employee.active.is_(True),
                    or_(Employee.termination_date.is_(None), Employee.termination_date >= today),
                    EmploymentContract.active.is_(True),
                    EmploymentContract.valid_from <= today,
                    or_(EmploymentContract.valid_to.is_(None), EmploymentContract.valid_to >= today),
                )
            ) or 0
            rows = session.scalars(
                select(PayrollRun).order_by(PayrollRun.period_start.desc(), PayrollRun.id.desc())
            ).all()
            payrolls = self._payrolls(session, rows)
            latest = next((payroll for payroll in payrolls if payroll.status != "draft"), payrolls[0] if payrolls else None)
            issued_receipts = session.scalar(
                select(func.count())
                .select_from(PayrollResult)
                .join(PayrollRun, PayrollRun.id == PayrollResult.payroll_run_id)
                .where(PayrollRun.status.in_(("APPROVED", "CLOSED")))
            ) or 0
            return {
                "companies": companies_count,
                "active_employees": active_employees,
                "in_review": sum(payroll.status in {"calculated", "review"} for payroll in payrolls),
                "pending_proposals": 0,
                "issued_receipts": issued_receipts,
                "latest_payroll": latest,
                "total_net": latest.net if latest else _ZERO,
                "total_gross": latest.gross if latest else _ZERO,
                "employer_cost": latest.employer_cost if latest else _ZERO,
            }


__all__ = ["SqlAlchemyDataSource"]
