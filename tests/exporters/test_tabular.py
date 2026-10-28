"""Descarga tabular de un modulo en csv, xlsx o json."""

from __future__ import annotations

import pytest

from app.exporters.tabular import normalize_format, render_table

ROWS = [
    {"legajo": "A1", "nombre": "Ana", "neto": "37284.45", "activo": True},
    {"legajo": "A2", "nombre": "Luis", "neto": None, "activo": False},
]
COLUMNS = ["legajo", "nombre", "neto", "activo"]


def test_rechaza_formato_desconocido() -> None:
    with pytest.raises(ValueError, match="Formato no soportado"):
        normalize_format("pdf")


def test_csv_con_bom_y_encabezado() -> None:
    raw = render_table(ROWS, COLUMNS, "csv")
    text = raw.decode("utf-8-sig")
    lines = text.strip().splitlines()
    assert lines[0] == "legajo,nombre,neto,activo"
    assert lines[1] == "A1,Ana,37284.45,True"


def test_xlsx_con_encabezado_y_celdas() -> None:
    from io import BytesIO

    from openpyxl import load_workbook

    sheet = load_workbook(BytesIO(render_table(ROWS, COLUMNS, "xlsx"))).active
    assert sheet is not None
    assert [cell.value for cell in sheet[1]] == COLUMNS
    assert [cell.value for cell in sheet[2]] == ["A1", "Ana", "37284.45", True]


def test_json_es_lista_de_objetos() -> None:
    import json

    # Las celdas vacias viajan como "" en los tres formatos.
    assert json.loads(render_table(ROWS, COLUMNS, "json")) == [
        {"legajo": "A1", "nombre": "Ana", "neto": "37284.45", "activo": True},
        {"legajo": "A2", "nombre": "Luis", "neto": "", "activo": False},
    ]
