"""Benchmark a monthly payroll in a disposable PostgreSQL schema."""
from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from datetime import date
from typing import cast
from uuid import uuid4

from alembic.config import Config
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker

from alembic import command
from app.config import get_settings
from app.database.models import (
    Company,
    Employee,
    EmploymentContract,
    Organization,
    PayrollItem,
    PayrollResult,
    PayrollRun,
    User,
)
from app.services.payroll_calculation import calculate_payroll_run
from scripts.seed_demo import seed


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("El valor debe ser mayor que cero")
    return number


def benchmark(url: str, employees: int, iterations: int) -> dict:
    parsed = make_url(url)
    if parsed.get_backend_name() != "postgresql":
        raise ValueError("Se requiere una URL PostgreSQL")
    schema = f"payroll_benchmark_{uuid4().hex}"
    admin_engine = create_engine(parsed)
    with admin_engine.begin() as db:
        db.execute(text(f'CREATE SCHEMA "{schema}"'))
    old_url = os.environ.get("PAYROLL_DATABASE_URL")
    scoped_url = parsed.update_query_dict({"options": f"-csearch_path={schema}"})
    os.environ["PAYROLL_DATABASE_URL"] = scoped_url.render_as_string(hide_password=False)
    get_settings.cache_clear()
    engine = create_engine(scoped_url)
    try:
        command.upgrade(Config("alembic.ini"), "head")
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        with factory.begin() as db:
            demo = seed(db)
            seeded = cast(list[Employee], demo["employees"])
            organization = cast(Organization, demo["organization"])
            company = cast(Company, demo["company"])
            admin = cast(User, demo["admin"])
            for employee in seeded[employees:]:
                employee.active = False
            source = db.scalar(select(EmploymentContract).where(
                EmploymentContract.employee_id == seeded[0].id,
                EmploymentContract.company_id == company.id,
            ))
            assert source is not None
            added = [Employee(
                organization_id=organization.id, employee_code=f"BENCH-{index:08d}",
                first_name="Prueba", last_name=f"Empleado {index}",
                hire_date=source.valid_from, active=True,
            ) for index in range(max(0, employees - len(seeded)))]
            db.add_all(added)
            db.flush()
            db.add_all([EmploymentContract(
                employee_id=employee.id, company_id=source.company_id,
                agreement_id=source.agreement_id, category_id=source.category_id,
                valid_from=source.valid_from, employment_type=source.employment_type,
                weekly_hours=source.weekly_hours, monthly_salary=source.monthly_salary, active=True,
            ) for employee in added])
            run = PayrollRun(
                organization_id=organization.id, company_id=company.id,
                created_by=admin.id, code="benchmark",
                period_start=date(2026, 6, 1), period_end=date(2026, 6, 30),
                run_type="MONTHLY", status="DRAFT",
            )
            db.add(run)
            db.flush()
            run_id = run.id
        elapsed, hashes = [], []
        for _ in range(iterations):
            with factory() as db:
                current_run = db.get(PayrollRun, run_id)
                assert current_run is not None
                started = time.perf_counter()
                response = calculate_payroll_run(db, current_run, include_items=False)
                db.commit()
                elapsed.append(round(time.perf_counter() - started, 6))
                if response["status"] != "CALCULATED" or response["summary"]["calculated"] != employees:
                    raise RuntimeError(f"Cálculo incompleto: {response['summary']}; {response['errors']}")
                hashes.append(response["results_hash"])
        with factory() as db:
            item_count, concept_count = db.execute(select(
                func.count(PayrollItem.id), func.count(func.distinct(PayrollItem.code)),
            ).join(PayrollResult).where(PayrollResult.payroll_run_id == run_id)).one()
            pg_version = db.scalar(text("SHOW server_version"))
        return {
            "employees": employees, "iterations": iterations,
            "concepts_distinct": concept_count, "concept_items": item_count,
            "elapsed_seconds": elapsed, "median_seconds": statistics.median(elapsed),
            "results_hashes_stable": len(set(hashes)) == 1, "results_hashes": hashes,
            "postgres_version": pg_version,
        }
    finally:
        engine.dispose()
        if old_url is None:
            os.environ.pop("PAYROLL_DATABASE_URL", None)
        else:
            os.environ["PAYROLL_DATABASE_URL"] = old_url
        get_settings.cache_clear()
        try:
            with admin_engine.begin() as db:
                db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        finally:
            admin_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("PAYROLL_TEST_POSTGRES_URL"))
    parser.add_argument("--employees", type=positive_int, default=1000)
    parser.add_argument("--iterations", type=positive_int, default=3)
    args = parser.parse_args()
    if not args.url:
        parser.error("Indique --url o PAYROLL_TEST_POSTGRES_URL")
    print(json.dumps(benchmark(args.url, args.employees, args.iterations), indent=2))


if __name__ == "__main__":
    main()
