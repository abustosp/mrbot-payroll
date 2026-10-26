from decimal import Decimal

from sqlalchemy import Numeric, UniqueConstraint

from app.database import Base
from app.database.models import (
    Company,
    EmploymentContract,
    FormulaVersion,
    PayrollItem,
    PayrollResult,
    SalaryScale,
)


def test_mvp_tables_and_money_types_are_registered() -> None:
    expected = {
        "organizations", "users", "companies", "establishments", "employees",
        "employment_contracts", "employment_history", "collective_agreements",
        "agreement_categories", "salary_scales", "payroll_concepts", "concept_tax_treatments",
        "formula_definitions", "formula_versions", "normative_parameters", "normative_documents",
        "ruleset_versions", "payroll_runs", "payroll_results", "payroll_items",
        "payroll_calculation_traces", "payroll_approvals", "audit_logs", "background_jobs",
    }
    assert expected <= set(Base.metadata.tables)
    assert isinstance(PayrollResult.__table__.c.gross.type, Numeric)
    assert PayrollResult.__table__.c.gross.type.precision == 18
    assert PayrollResult.__table__.c.gross.type.scale == 4
    assert isinstance(PayrollItem.__table__.c.amount.type, Numeric)
    assert isinstance(SalaryScale.__table__.c.base_salary.type, Numeric)
    assert Decimal("0.1000") + Decimal("0.2000") == Decimal("0.3000")


def test_keys_and_inclusive_validity_constraints_exist() -> None:
    assert any(isinstance(item, UniqueConstraint) and {"cuit"} == {column.name for column in item.columns} for item in Company.__table__.constraints)
    for model in (EmploymentContract, SalaryScale, FormulaVersion):
        checks = [str(item.sqltext) for item in model.__table__.constraints if getattr(item, "sqltext", None) is not None]
        assert any("valid_to" in check and ">=" in check for check in checks)
