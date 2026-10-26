from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO, StringIO

from openpyxl import Workbook

from app.importers import analyze_file, import_rows

VALID_CUIL_1 = "20123456786"
VALID_CUIL_2 = "27123456780"

EMPLOYEE_HEADERS = [
    "Legajo",
    "Apellido",
    "Nombre",
    "CUIL",
    "Fecha de ingreso",
    "Categoría",
    "Convenio",
    "Email",
]


def employee_csv(rows: list[str]) -> str:
    header = ";".join(EMPLOYEE_HEADERS)
    return "\n".join([header, *rows]) + "\n"


def make_xlsx(headers: list[str], rows: list[list[object]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.append(headers)
    for row in rows:
        worksheet.append(row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_csv_valido_empleados() -> None:
    content = employee_csv(
        [
            "1;Pérez;Juan;20-12345678-6;15/03/2024;Administrativo;CCT 130/75;"
            "juan.perez@example.com"
        ]
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.kind == "employees"
    assert preview.total == 1
    assert preview.dry_run is True
    assert preview.errors == []
    assert preview.duplicates == []
    assert preview.missing_columns == []
    assert preview.mapping["legajo"] == "Legajo"
    assert preview.mapping["fecha_ingreso"] == "Fecha de ingreso"
    row = preview.valid_rows[0]
    assert row.legajo == "1"
    assert row.apellido == "Pérez"
    assert row.cuil == VALID_CUIL_1
    assert row.fecha_ingreso == date(2024, 3, 15)
    assert row.categoria == "Administrativo"
    assert row.email == "juan.perez@example.com"


def test_csv_con_delimitador_coma() -> None:
    content = (
        ",".join(EMPLOYEE_HEADERS)
        + "\n"
        + "2,Pérez,Ana,20-12345678-6,16/03/2024,Administrativa,CCT,ana@example.com\n"
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.errors == []
    assert preview.total == 1
    assert preview.valid_rows[0].legajo == "2"


def test_xlsx_valido_dos_filas() -> None:
    content = make_xlsx(
        EMPLOYEE_HEADERS,
        [
            ["1", "Pérez", "Ana", "20-12345678-6", date(2024, 1, 10), "Admin", "CCT", None],
            ["2", "Gómez", "Luis", "27-12345678-0", "15/06/2024", "Técnico", "CCT", None],
        ],
    )

    preview = analyze_file(BytesIO(content), "employees")

    assert preview.total == 2
    assert len(preview.valid_rows) == 2
    assert preview.errors == []
    assert preview.duplicates == []
    assert preview.valid_rows[0].fecha_ingreso == date(2024, 1, 10)
    assert preview.valid_rows[1].fecha_ingreso == date(2024, 6, 15)


def test_csv_latin1() -> None:
    content = employee_csv(
        ["7;Muñoz;Raúl;20-12345678-6;01/02/2024;Técnico;Convenio;Café@example.com"]
    ).encode("latin-1")

    preview = analyze_file(BytesIO(content), "employees")

    assert preview.errors == []
    row = preview.valid_rows[0]
    assert row.apellido == "Muñoz"
    assert row.nombre == "Raúl"
    assert row.categoria == "Técnico"
    assert row.email == "Café@example.com"


def test_csv_utf8_sig_y_stringio() -> None:
    content = employee_csv(
        ["3;Sosa;María;20-12345678-6;2024-04-01;Administrativa;CCT;maria@example.com"]
    )

    preview = analyze_file(StringIO(content.encode("utf-8-sig").decode("utf-8-sig")), "employees")
    assert preview.errors == []
    assert preview.valid_rows[0].nombre == "María"

    preview_bom = analyze_file(BytesIO(content.encode("utf-8-sig")), "employees")
    assert preview_bom.errors == []
    assert preview_bom.valid_rows[0].legajo == "3"


def test_monto_argentino_y_periodos() -> None:
    content = (
        "Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\n"
        "1;202609;Horas extra;2,5;1.234,56;Horas autorizadas\n"
        "2;2026-10;Comisión;1;1234.56;Comisión mensual\n"
        "3;09/2026;Adelanto;;1.000,00;\n"
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "novelties")

    assert preview.errors == []
    assert preview.total == 3
    assert len(preview.valid_rows) == 3
    assert [row.importe for row in preview.valid_rows] == [
        Decimal("1234.56"),
        Decimal("1234.56"),
        Decimal("1000.00"),
    ]
    assert preview.valid_rows[0].cantidad == Decimal("2.5")
    assert preview.valid_rows[0].tipo == "horas_extra"
    assert preview.valid_rows[1].tipo == "comision"
    assert preview.valid_rows[2].tipo == "adelanto"
    assert preview.valid_rows[0].periodo == "202609"
    assert preview.valid_rows[1].periodo == "202610"
    assert preview.valid_rows[2].periodo == "202609"


def test_cuil_invalido() -> None:
    content = employee_csv(
        ["1;Pérez;Juan;20-12345678-7;15/03/2024;Administrativo;CCT;"]
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 1
    assert preview.valid_rows == []
    assert len(preview.errors) == 1
    error = preview.errors[0]
    assert error.row == 2
    assert error.field == "cuil"
    assert error.code == "cuil_invalido"


def test_fecha_invalida() -> None:
    content = employee_csv(
        ["1;Pérez;Juan;20-12345678-6;31/02/2024;Administrativo;CCT;"]
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.valid_rows == []
    assert len(preview.errors) == 1
    assert preview.errors[0].field == "fecha_ingreso"
    assert preview.errors[0].code == "fecha_invalida"


def test_duplicado_por_legajo() -> None:
    content = employee_csv(
        [
            "1;Pérez;Juan;20-12345678-6;15/03/2024;Administrativo;CCT;",
            "1;Pérez;Juan;20-12345678-6;15/03/2024;Administrativo;CCT;",
        ]
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 2
    assert len(preview.valid_rows) == 1
    assert preview.errors == []
    assert len(preview.duplicates) == 1
    duplicate = preview.duplicates[0]
    assert duplicate.row == 3
    assert duplicate.first_row == 2
    assert "legajo" in duplicate.key


def test_columna_faltante() -> None:
    content = (
        "Legajo;Apellido;Nombre;Fecha de ingreso\n"
        "1;Pérez;Juan;15/03/2024\n"
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 1
    assert preview.valid_rows == []
    assert preview.missing_columns == ["cuil"]
    assert any(
        error.field == "cuil" and error.code == "columna_faltante"
        for error in preview.errors
    )


def test_archivo_vacio() -> None:
    preview = analyze_file(BytesIO(b""), "employees")

    assert preview.total == 0
    assert preview.valid_rows == []
    assert len(preview.errors) == 1
    assert preview.errors[0].code == "archivo_vacio"
    assert preview.dry_run is True


def test_archivo_solo_encabezados() -> None:
    content = ";".join(EMPLOYEE_HEADERS) + "\n"

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 0
    assert preview.valid_rows == []
    assert len(preview.errors) == 1
    assert preview.errors[0].code == "sin_datos"


def test_ruta_de_archivo_csv(tmp_path) -> None:
    path = tmp_path / "empleados.csv"
    path.write_text(
        employee_csv(
            ["11;Acosta;Julia;20-12345678-6;2024-09-01;Administrativa;CCT;"]
        ),
        encoding="utf-8",
    )

    preview = analyze_file(str(path), "employees")

    assert preview.errors == []
    assert preview.valid_rows[0].legajo == "11"


def test_una_fila_invalida_no_detiene_el_resto() -> None:
    content = employee_csv(
        [
            "1;Pérez;Juan;20-12345678-6;15/03/2024;Administrativo;CCT;",
            "2;Gómez;Luis;20-12345678-0;15/03/2024;Administrativo;CCT;",
            "3;Sosa;Ana;27-12345678-0;2024-03-15;Administrativo;CCT;",
        ]
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 3
    assert len(preview.valid_rows) == 2
    assert len(preview.errors) == 1
    assert preview.errors[0].row == 3
    assert preview.errors[0].field == "cuil"


def test_import_rows_desde_diccionarios() -> None:
    rows = [
        {
            "Legajo": "9",
            "Apellido": "López",
            "Nombre": "Sofía",
            "CUIL": "20-12345678-6",
            "Fecha de ingreso": "2024-07-01",
            "Categoría": "Administrativa",
        }
    ]

    result = import_rows(rows, "employees")

    assert result.kind == "employees"
    assert result.total == 1
    assert result.dry_run is True
    assert result.errors == []
    row = result.valid_rows[0]
    assert row.legajo == "9"
    assert row.apellido == "López"
    assert row.fecha_ingreso == date(2024, 7, 1)


def test_import_rows_reutiliza_preview() -> None:
    content = employee_csv(
        ["4;Díaz;Pedro;20-12345678-6;15/03/2024;Administrativo;CCT;"]
    )
    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    result = import_rows(preview.valid_rows, "employees")

    assert result.total == 1
    assert result.errors == []
    assert result.valid_rows[0].legajo == "4"


def test_mapping_explicito() -> None:
    content = (
        "Nro;Apellido;Nombre;Documento;Alta\n"
        "12;Petracca;María;20-12345678-6;2024-08-01\n"
    )

    preview = analyze_file(
        BytesIO(content.encode("utf-8")),
        "employees",
        mapping={
            "legajo": "Nro",
            "cuil": "Documento",
            "fecha_ingreso": "Alta",
        },
    )

    assert preview.errors == []
    assert preview.mapping["legajo"] == "Nro"
    assert preview.valid_rows[0].legajo == "12"
    assert preview.valid_rows[0].cuil == VALID_CUIL_1


def test_mapping_explicito_invertido() -> None:
    content = (
        "Nro;Apellido;Nombre;Documento;Fecha contratacion\n"
        "13;Petracca;María;20-12345678-6;2024-08-01\n"
    )

    preview = analyze_file(
        BytesIO(content.encode("utf-8")),
        "employees",
        mapping={
            "Nro": "legajo",
            "Documento": "cuil",
            "Fecha contratacion": "fecha_ingreso",
        },
    )

    assert preview.errors == []
    assert preview.mapping["legajo"] == "Nro"
    assert preview.mapping["fecha_ingreso"] == "Fecha contratacion"
    assert preview.valid_rows[0].legajo == "13"
    assert preview.valid_rows[0].fecha_ingreso == date(2024, 8, 1)


def test_columna_horas_extra_implica_tipo_y_cantidad() -> None:
    content = (
        "Legajo;Periodo;Horas extra;Observación\n"
        "5;202609;3,5;Horas al 50%\n"
    )

    preview = analyze_file(BytesIO(content.encode("utf-8")), "novelties")

    assert preview.errors == []
    assert preview.mapping["tipo"] == "Horas extra"
    assert preview.mapping["cantidad"] == "Horas extra"
    row = preview.valid_rows[0]
    assert row.tipo == "horas_extra"
    assert row.cantidad == Decimal("3.5")


def test_serial_excel_en_fecha_y_periodo() -> None:
    content = employee_csv(
        ["6;Ríos;Ana;20-12345678-6;45292;Administrativa;CCT;"]
    )
    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")
    assert preview.errors == []
    assert preview.valid_rows[0].fecha_ingreso == date(2024, 1, 1)

    novelty_csv = "Legajo;Periodo;Tipo;Importe\n6;46266;Comisión;10\n"
    novelty = analyze_file(BytesIO(novelty_csv.encode("utf-8")), "novelties")
    assert novelty.errors == []
    assert novelty.valid_rows[0].periodo == "202609"


def test_columna_faltante_sin_filas_reporta_error_de_header() -> None:
    content = "Legajo;Apellido;Fecha de ingreso\n"

    preview = analyze_file(BytesIO(content.encode("utf-8")), "employees")

    assert preview.total == 0
    assert preview.missing_columns == ["nombre", "cuil"]
    assert {error.field for error in preview.errors} == {"nombre", "cuil"}
    assert all(error.row == 1 for error in preview.errors)


def test_tipo_de_importacion_invalido() -> None:
    try:
        analyze_file(BytesIO(b""), "desconocido")
    except ValueError as exc:
        assert "employees" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("Se esperaba ValueError")
