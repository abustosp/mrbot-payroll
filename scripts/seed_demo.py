"""Create the repeatable, illustrative demo organization and payroll data."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.auth.security import hash_password
from app.database import Base
from app.database.models import (
    AgreementCategory,
    CollectiveAgreement,
    Company,
    Employee,
    EmploymentContract,
    FormulaDefinition,
    FormulaVersion,
    NormativeParameter,
    Organization,
    PayrollConcept,
    SalaryScale,
    User,
)
from app.database.session import SessionLocal, engine

DEMO_START = date(2026, 1, 1)
DEMO_END = date(2026, 12, 31)


def _tax_id(prefix: str, sequence: int) -> str:
    body = f"{prefix}{sequence:08d}"
    weights = (5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
    remainder = 11 - sum(int(digit) * weight for digit, weight in zip(body, weights, strict=True)) % 11
    verifier = 0 if remainder == 11 else 9 if remainder == 10 else remainder
    return f"{body}{verifier}"


def seed(session: Session) -> dict[str, object]:
    """Upsert all demo records without committing the caller's transaction."""

    organization = session.scalar(select(Organization).where(Organization.slug == "payroll-demo"))
    if organization is None:
        organization = Organization(name="Organización Demo", slug="payroll-demo")
        session.add(organization)
        session.flush()

    # V2-02: solo crear el admin si no existe; jamas re-escribir una fila
    # existente (rotar la contrasena debe sobrevivir a un re-seed).
    admin = session.scalar(select(User).where(User.email == "admin@example.com"))
    if admin is None:
        admin = User(
            organization_id=organization.id,
            email="admin@example.com",
            password_hash=hash_password("admin"),
            role="admin",
        )
        session.add(admin)
        session.flush()

    employer_cuit = _tax_id("30", 71234567)
    company = session.scalar(select(Company).where(Company.cuit == employer_cuit))
    if company is None:
        company = Company(
            organization_id=organization.id,
            cuit=employer_cuit,
            legal_name="Empresa Demo S.A.",
            trade_name="Empresa Demo",
            tax_activity="Comercio",
            address="Av. Demo 123, Buenos Aires",
        )
        session.add(company)
        session.flush()
    else:
        company.organization_id = organization.id
        company.legal_name = "Empresa Demo S.A."
        company.trade_name = "Empresa Demo"
        company.tax_activity = "Comercio"
        company.address = "Av. Demo 123, Buenos Aires"
        company.active = True

    agreement = session.scalar(
        select(CollectiveAgreement).where(
            CollectiveAgreement.code == "130/75",
            CollectiveAgreement.year == 1975,
        )
    )
    if agreement is None:
        agreement = CollectiveAgreement(
            code="130/75",
            year=1975,
            name="Empleados de Comercio",
            activity="Comercio",
            scope="Datos demostrativos para el MVP.",
        )
        session.add(agreement)
        session.flush()
    categories: dict[str, AgreementCategory] = {}
    for code, name in (("ADMIN_A", "Administrativo A"), ("ADMIN_B", "Administrativo B")):
        category = session.scalar(
            select(AgreementCategory).where(
                AgreementCategory.agreement_id == agreement.id,
                AgreementCategory.code == code,
            )
        )
        if category is None:
            category = AgreementCategory(agreement_id=agreement.id, code=code, name=name)
            session.add(category)
            session.flush()
        else:
            category.name = name
        categories[code] = category

    for code, amount in (("ADMIN_A", "850000.00"), ("ADMIN_B", "900000.00")):
        scale = session.scalar(
            select(SalaryScale).where(
                SalaryScale.category_id == categories[code].id,
                SalaryScale.valid_from == DEMO_START,
            )
        )
        if scale is None:
            scale = SalaryScale(
                category_id=categories[code].id,
                valid_from=DEMO_START,
                valid_to=DEMO_END,
                base_salary=Decimal(amount),
                additional=Decimal("0"),
            )
            session.add(scale)
        else:
            scale.valid_to = DEMO_END
            scale.base_salary = Decimal(amount)
            scale.additional = Decimal("0")

    employees: list[Employee] = []
    employee_specs = (
        ("E-001", "Ana", "Pérez", "20", 12345678, date(2018, 3, 12), "ADMIN_A"),
        ("E-002", "Luis", "Gómez", "27", 87654321, date(2021, 7, 1), "ADMIN_B"),
    )
    for code, first_name, last_name, prefix, number, hire_date, category_code in employee_specs:
        cuil = _tax_id(prefix, number)
        employee = session.scalar(
            select(Employee).where(
                Employee.organization_id == organization.id,
                Employee.employee_code == code,
            )
        )
        if employee is None:
            employee = Employee(
                organization_id=organization.id,
                employee_code=code,
                first_name=first_name,
                last_name=last_name,
                cuil=cuil,
                hire_date=hire_date,
                active=True,
            )
            session.add(employee)
            session.flush()
        else:
            employee.first_name = first_name
            employee.last_name = last_name
            employee.cuil = cuil
            employee.hire_date = hire_date
            employee.active = True

        contract = session.scalar(
            select(EmploymentContract).where(
                EmploymentContract.employee_id == employee.id,
                EmploymentContract.company_id == company.id,
                EmploymentContract.valid_from == hire_date,
            )
        )
        if contract is None:
            contract = EmploymentContract(
                employee_id=employee.id,
                company_id=company.id,
                agreement_id=agreement.id,
                category_id=categories[category_code].id,
                valid_from=hire_date,
                employment_type="full_time",
                weekly_hours=Decimal("48"),
                active=True,
            )
            session.add(contract)
        else:
            contract.agreement_id = agreement.id
            contract.category_id = categories[category_code].id
            contract.valid_to = None
            contract.active = True
        employees.append(employee)

    concepts = (
        ("BASICO", "Sueldo básico", "REMUNERATIVE"),
        ("ANTIGUEDAD", "Antigüedad", "REMUNERATIVE"),
        ("JUBILACION", "Descuento jubilatorio demo", "DEDUCTION"),
    )
    concept_rows: dict[str, PayrollConcept] = {}
    for code, name, nature in concepts:
        concept = session.scalar(
            select(PayrollConcept).where(
                PayrollConcept.organization_id == organization.id,
                PayrollConcept.code == code,
            )
        )
        if concept is None:
            concept = PayrollConcept(
                organization_id=organization.id,
                code=code,
                name=name,
                nature=nature,
                description="Regla de ejemplo; no representa una liquidación normativa.",
            )
            session.add(concept)
            session.flush()
        else:
            concept.name = name
            concept.nature = nature
            concept.active = True
        concept_rows[code] = concept

    expressions: dict[str, dict[str, Any]] = {
        "BASICO": {"variable": "sueldo_basico"},
        "ANTIGUEDAD": {
            "operator": "multiply",
            "arguments": [
                {"concept": "BASICO"},
                {"variable": "años_antiguedad"},
                {"parameter": "demo.cct13075.seniority_rate"},
            ],
        },
        "JUBILACION": {
            "operator": "multiply",
            "arguments": [
                {
                    "operator": "add",
                    "arguments": [{"concept": "BASICO"}, {"concept": "ANTIGUEDAD"}],
                },
                {"parameter": "demo.employee.retirement_rate"},
            ],
        },
    }
    for code, name, _nature in concepts:
        formula = session.scalar(
            select(FormulaDefinition).where(
                FormulaDefinition.organization_id == organization.id,
                FormulaDefinition.code == code,
            )
        )
        if formula is None:
            formula = FormulaDefinition(
                organization_id=organization.id,
                code=code,
                description=name,
                current_version=1,
            )
            session.add(formula)
            session.flush()
        else:
            formula.description = name
            formula.current_version = 1
        version = session.scalar(
            select(FormulaVersion).where(
                FormulaVersion.formula_id == formula.id,
                FormulaVersion.version == 1,
            )
        )
        if version is None:
            version = FormulaVersion(
                formula_id=formula.id,
                version=1,
                expression=expressions[code],
                status="APPROVED",
                valid_from=DEMO_START,
                valid_to=DEMO_END,
                approved_by=admin.id,
                approved_at=datetime.now(UTC),
            )
            session.add(version)
        else:
            version.expression = expressions[code]
            version.status = "APPROVED"
            version.valid_from = DEMO_START
            version.valid_to = DEMO_END
            version.approved_by = admin.id
            version.approved_at = datetime.now(UTC)

    for code, value in (
        ("demo.cct13075.seniority_rate", "0.01"),
        ("demo.employee.retirement_rate", "0.11"),
    ):
        parameter = session.scalar(
            select(NormativeParameter).where(
                NormativeParameter.jurisdiction == "AR",
                NormativeParameter.code == code,
                NormativeParameter.agreement_code == "",
                NormativeParameter.category_code == "",
                NormativeParameter.valid_from == DEMO_START,
                NormativeParameter.version == 1,
            )
        )
        if parameter is None:
            session.add(NormativeParameter(
                jurisdiction="AR",
                code=code,
                value=Decimal(value),
                valid_from=DEMO_START,
                valid_to=DEMO_END,
                published_at=DEMO_START,
                version=1,
            ))
        else:
            parameter.value = Decimal(value)
            parameter.valid_to = DEMO_END
            parameter.published_at = DEMO_START

    session.flush()
    return {
        "organization": organization,
        "admin": admin,
        "company": company,
        "employees": employees,
        "concepts": concept_rows,
    }


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description="Crea o actualiza los datos demo (idempotente, no duplica)."
    )
    parser.parse_args(argv)
    try:
        Base.metadata.create_all(bind=engine)
        with SessionLocal.begin() as session:
            seed(session)
    except OperationalError as exc:
        # B-62: la base existe con un esquema anterior o no es accesible.
        print(
            "No se pudo sembrar: la base no es accesible o tiene un esquema "
            "anterior. Ejecutá `alembic upgrade head` y reintentá.",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc
    # B-22: create_all no deja version de alembic y el upgrade posterior falla
    # con "table ... already exists"; sellar head tras crear (idempotente).
    from alembic.command import stamp
    from alembic.config import Config

    from app.config import get_settings

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
    stamp(config, "head")
    print("Seed demo listo: admin@example.com y 2 empleados (datos ilustrativos).")


if __name__ == "__main__":
    main()
