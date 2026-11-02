"""Suma a la demo los conceptos de novedades mensuales (horas extra, comisión, bonificación, adelanto).

Aditivo e idempotente: no modifica ``seed_demo``. Cada fórmula usa ``coalesce`` para valer 0
cuando el empleado no tiene esa novedad en el período. Uso: python -m scripts.seed_demo_novelties
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from app.database.models import (
    FormulaDefinition,
    FormulaVersion,
    Organization,
    PayrollConcept,
    User,
)
from app.database.session import SessionLocal
from scripts.seed_demo import DEMO_END, DEMO_START

NOVELTIES = (
    ("HORAS_EXTRA", "Horas extra", "REMUNERATIVE", "horas_extra"),
    ("COMISION", "Comisión", "REMUNERATIVE", "comision"),
    ("BONIFICACION", "Bonificación", "REMUNERATIVE", "bonificacion"),
    ("ADELANTO", "Adelanto de sueldo", "DEDUCTION", "adelanto"),
)


def seed_novelties(session) -> int:
    org = session.scalar(select(Organization).where(Organization.slug == "payroll-demo"))
    admin = session.scalar(select(User).where(User.email == "admin@example.com"))
    created = 0
    for code, name, nature, variable in NOVELTIES:
        if session.scalar(select(PayrollConcept).where(PayrollConcept.organization_id == org.id, PayrollConcept.code == code)):
            continue
        session.add(PayrollConcept(organization_id=org.id, code=code, name=name, nature=nature,
                                   description="Novedad mensual de ejemplo; no representa una liquidación normativa."))
        formula = FormulaDefinition(organization_id=org.id, code=code, description=name, current_version=1)
        session.add(formula)
        session.flush()
        session.add(FormulaVersion(
            formula_id=formula.id, version=1, status="APPROVED", valid_from=DEMO_START, valid_to=DEMO_END,
            expression={"operator": "coalesce", "arguments": [{"variable": variable}, {"constant": 0}]},
            approved_by=admin.id, approved_at=datetime.now(UTC),
        ))
        created += 1
    return created


if __name__ == "__main__":
    with SessionLocal.begin() as session:
        print(f"Conceptos de novedades creados: {seed_novelties(session)}")
