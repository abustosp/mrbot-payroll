"""V2-31: pin de presupuesto F931 (N=300, 900 items) + PDF unitario.

Pin de bytes estricto (falla si x2: F931 <= 110 KB, PDF <= 50 KB, medidos
~54 KB / ~24 KB sin coverage). El tiempo se pinnea generoso (<= 2,5 s / 2,0 s)
porque bajo ``--cov`` WeasyPrint/openpyxl se enlentecen 2-3x; un tiempo mayor
indica regresion grave, no microvariacion. Topes documentados en los modulos.
"""

from __future__ import annotations

import time
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

from app.exporters.excel.f931 import build_f931_workbook
from app.exporters.pdf.receipts import render_receipt_pdf

N = 300


def _synthetic_run() -> tuple:
    run = SimpleNamespace(
        id=1,
        code="LIQ-2026-06",
        period_start=date(2026, 6, 1),
        period_end=date(2026, 6, 30),
        status="CALCULATED",
        run_type="MONTHLY",
    )
    company = SimpleNamespace(legal_name="Empresa Test", cuit="30712345678")
    results: list = []
    items: list = []
    employees: list = []
    item_id = 1
    for index in range(1, N + 1):
        employees.append(
            SimpleNamespace(
                id=index,
                first_name=f"Nombre{index}",
                last_name=f"Apellido{index}",
                cuil="20123456786",
                employee_code=f"E-{index:04d}",
            )
        )
        results.append(
            SimpleNamespace(
                id=index,
                payroll_run_id=1,
                employee_id=index,
                remunerative=Decimal("100000"),
                non_remunerative=Decimal("5000"),
                deductions=Decimal("15000"),
                contributions=Decimal("20000"),
                gross=Decimal("105000"),
                net=Decimal("90000"),
                employer_cost=Decimal("125000"),
            )
        )
        for code in ("BASICO", "ANTIG", "APORTE"):
            items.append(
                SimpleNamespace(
                    id=item_id,
                    payroll_result_id=index,
                    employee_id=index,
                    code=code,
                    description=f"Concepto {code}",
                    nature="REMUNERATIVE",
                    quantity=Decimal("1"),
                    unit_value=None,
                    amount=Decimal("10000.00"),
                )
            )
            item_id += 1
    return run, results, items, employees, company


def test_v2_31_f931_n300_bytes_y_tiempo() -> None:
    run, results, items, employees, company = _synthetic_run()
    started = time.perf_counter()
    payload = build_f931_workbook(run, results, items, employees, company)
    elapsed = time.perf_counter() - started
    assert len(payload) <= 110 * 1024, len(payload)
    assert elapsed <= 2.5, round(elapsed, 3)


def test_v2_31_pdf_unitario_bytes_y_tiempo() -> None:
    context = {
        "receipt_number": "R-2026-09-0001",
        "issue_date": date(2026, 9, 30),
        "period": "Septiembre 2026",
        "employer": {"name": "Andes", "cuit": "30-71234567-8"},
        "employee": {"name": "Test User", "cuil": "20-12345678-6"},
        "items": [
            {
                "code": "BASICO",
                "name": "Basico",
                "kind": "remunerative",
                "amount": "100000.00",
            }
        ],
        "net": "85000.00",
    }
    render_receipt_pdf(context)  # warm-up WeasyPrint
    started = time.perf_counter()
    payload = render_receipt_pdf(context)
    elapsed = time.perf_counter() - started
    assert payload.startswith(b"%PDF")
    assert len(payload) <= 50 * 1024, len(payload)
    assert elapsed <= 2.0, round(elapsed, 3)
