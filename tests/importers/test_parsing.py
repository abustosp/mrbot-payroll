from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

import pytest

from app.importers.parsing import (
    cuil_check_digit,
    is_valid_cuil,
    normalize_cuil,
    normalize_naturaleza,
    normalize_text,
    normalize_tipo,
    parse_date,
    parse_decimal,
    parse_periodo,
    parse_quincena,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1.234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("1234,56", Decimal("1234.56")),
        ("1.234", Decimal("1234")),
        ("1,234", Decimal("1234")),
        ("1.234.567,89", Decimal("1234567.89")),
        ("$ 1.234,56", Decimal("1234.56")),
        ("ARS 1.234,56", Decimal("1234.56")),
        ("(1.234,56)", Decimal("-1234.56")),
        ("-1.234,56", Decimal("-1234.56")),
        (1234.5, Decimal("1234.5")),
        (0, Decimal("0")),
        ("", None),
        ("   ", None),
        ("abc", None),
        ("1.2.3", None),
        (None, None),
        (True, None),
    ],
)
def test_parse_decimal(raw: object, expected: Decimal | None) -> None:
    assert parse_decimal(raw) == expected


def test_parse_decimal_redondea_importes_a_dos_decimales() -> None:
    assert parse_decimal("1.234,567", places=2) == Decimal("1234.57")


def test_cuil_valido_y_digito_verificador() -> None:
    assert cuil_check_digit("2012345678") == 6
    assert is_valid_cuil("20-12345678-6") is True
    assert is_valid_cuil("20123456786") is True
    assert is_valid_cuil("20123456787") is False
    assert is_valid_cuil("2012345678") is False
    assert is_valid_cuil("2012345678A") is False
    assert normalize_cuil("20-12345678-6") == "20123456786"
    assert normalize_cuil(20123456786) == "20123456786"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("15/03/2024", date(2024, 3, 15)),
        ("15-03-2024", date(2024, 3, 15)),
        ("2024-03-15", date(2024, 3, 15)),
        ("2024/03/15", date(2024, 3, 15)),
        ("15/03/24", date(2024, 3, 15)),
        ("20240315", date(2024, 3, 15)),
        (20240315, date(2024, 3, 15)),
        (45292, date(2024, 1, 1)),
        ("45292", date(2024, 1, 1)),
        (datetime(2024, 3, 15, 13, 45), date(2024, 3, 15)),
        (date(2024, 3, 15), date(2024, 3, 15)),
        ("31/02/2024", None),
        ("2024-13-01", None),
        ("no es fecha", None),
        ("", None),
    ],
)
def test_parse_date(raw: object, expected: date | None) -> None:
    assert parse_date(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("202609", "202609"),
        (202609, "202609"),
        ("2026-09", "202609"),
        ("09/2026", "202609"),
        ("2026/09", "202609"),
        ("septiembre 2026", "202609"),
        ("septiembre de 2026", "202609"),
        ("01/09/2026", "202609"),
        ("2026-09-01", "202609"),
        (date(2026, 9, 1), "202609"),
        (datetime(2026, 9, 1, 8, 0), "202609"),
        (46266, "202609"),
        ("202613", None),
        ("13/2026", None),
        ("31/02/2024", None),
        ("", None),
    ],
)
def test_parse_periodo(raw: object, expected: str | None) -> None:
    assert parse_periodo(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Horas Extra", "horas_extra"),
        ("Horas extras", "horas_extra"),
        ("Comisión", "comision"),
        ("Aguinaldo", "sac"),
        ("Ausencias", "ausencia"),
        ("  ", None),
        ("123", None),
    ],
)
def test_normalize_tipo(raw: str, expected: str | None) -> None:
    assert normalize_tipo(raw) == expected


def test_normalize_text_quita_acentos_y_espacios() -> None:
    assert normalize_text("  Fecha   de Ingreso ") == "fecha de ingreso"
    assert normalize_text("Período") == "periodo"
    assert normalize_text("C.U.I.L.") == "c u i l"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Remunerativo", "REMUNERATIVE"),
        ("NR", "NON_REMUNERATIVE"),
        ("no remunerativa", "NON_REMUNERATIVE"),
        ("Descuento", "DEDUCTION"),
        ("Contribución", "CONTRIBUTION"),
        ("AUX", "AUXILIARY"),
        ("XYZ", None),
        ("", None),
    ],
)
def test_normalize_naturaleza(raw: str, expected: str | None) -> None:
    assert normalize_naturaleza(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (1, 1),
        ("2", 2),
        ("Q1", 1),
        ("segunda", 2),
        (3, None),
        ("0", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_quincena(raw: object, expected: int | None) -> None:
    assert parse_quincena(raw) == expected
