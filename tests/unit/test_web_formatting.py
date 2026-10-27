"""Cobertura directa de los helpers de presentación web (puros, sin I/O)."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from app.web.formatting import (
    date_ar,
    initials,
    kind_label,
    money,
    percent,
    period_ar,
    progress_width,
    quantity,
    status_class,
    status_label,
    to_decimal,
    truncate,
)


def test_to_decimal_edge_cases() -> None:
    assert to_decimal(None) is None
    assert to_decimal("") is None
    assert to_decimal(True) is None
    assert to_decimal(Decimal("1.5")) == Decimal("1.5")
    assert to_decimal("12.5") == Decimal("12.5")
    assert to_decimal("no-numero") is None
    assert to_decimal(object()) is None


def test_money_formats_argentine_style() -> None:
    assert money(1234567.89) == "$ 1.234.567,89"
    assert money("1000") == "$ 1.000,00"
    assert money(Decimal("-5.2")) == "-$ 5,20"
    assert money(None) == "—"
    assert money("xyz") == "—"


def test_quantity_omits_decimals_for_integers() -> None:
    assert quantity(30) == "30"
    assert quantity(2.5) == "2,50"
    assert quantity(None) == "—"


def test_percent_uses_comma() -> None:
    assert percent(12.5) == "12,5%"
    assert percent(None) == "—"


def test_progress_width_clamps_and_rejects_non_positive_top() -> None:
    assert progress_width(50) == "50.0%"
    assert progress_width(150) == "100.0%"
    assert progress_width(-3) == "0.0%"
    assert progress_width(10, maximum=0) == "10.0%"
    assert progress_width(10, maximum=-5) == "0%"
    assert progress_width(None) == "0%"


def test_date_ar_accepts_several_shapes() -> None:
    assert date_ar(date(2026, 7, 31)) == "31/07/2026"
    assert date_ar(datetime(2026, 7, 31, 10, 0)) == "31/07/2026"
    assert date_ar("2026-07-31") == "31/07/2026"
    assert date_ar("2026-07") == "01/07/2026"
    assert date_ar(None) == "—"
    assert date_ar("") == "—"
    assert date_ar("31/07/2026") == "31/07/2026"
    assert date_ar("invalida") == "invalida"


def test_period_ar_converts_yyyymm() -> None:
    assert period_ar("2026-09") == "09/2026"
    assert period_ar("202609") == "202609"
    assert period_ar(None) == "—"


def test_status_label_and_class_cover_domains_and_fallback() -> None:
    assert status_label("active", "company") == "Activa"
    assert status_label("ACTIVE", "company") == "Activa"
    assert status_label("calculated", "payroll") == "Calculada"
    assert status_label("in_review", "proposal") == "En revisión"
    assert status_label("desconocido") == "Desconocido"
    assert status_class("approved") == "success"
    assert status_class("REJECTED") == "danger"
    assert status_class("raro") == "neutral"


def test_kind_label_falls_back_to_raw() -> None:
    assert kind_label("remunerative") == "Remunerativo"
    assert kind_label("DEDUCTION") == "Descuento"
    assert kind_label("otro") == "otro"


def test_initials_and_truncate() -> None:
    assert initials("") == "?"
    assert initials("María") == "MA"
    assert initials("Juan Pérez Gómez") == "JG"
    assert truncate("corto") == "corto"
    assert truncate("x" * 100) == "x" * 89 + "…"
    assert truncate(None) == ""
