"""Fix2 importers: V2-12 (formula riesgosa), V2-13 (< >), B-47P (CUIL 11 digitos).

Cobertura minima por item, en el layout normal del repo.
"""

from __future__ import annotations

from io import BytesIO

from app.importers import analyze_file

VALID_CUIL = "20-12345678-6"


def _employees_csv(rows: list[str]) -> bytes:
    header = "Legajo;Apellido;Nombre;CUIL;Fecha de ingreso"
    return ("\n".join([header, *rows]) + "\n").encode("utf-8")


def test_v2_12_formula_riesgosa_avisa_en_preview() -> None:
    content = _employees_csv(
        ["=cmd|'/c calc'!A0;Pérez;Juan;20-12345678-6;15/03/2024"]
    )
    preview = analyze_file(BytesIO(content), "employees")
    assert any(w.code == "formula_riesgosa" for w in preview.warnings)


def test_v2_12_mas_menos_arroba_tambien_avisan() -> None:
    for risky in ("+cmd", "-cmd", "@SUM(A1)"):
        content = _employees_csv(
            [f"1;{risky};Juan;20-12345678-6;15/03/2024"]
        )
        preview = analyze_file(BytesIO(content), "employees")
        assert any(w.code == "formula_riesgosa" for w in preview.warnings), risky


def test_v2_12_importe_negativo_no_es_formula_riesgosa() -> None:
    content = (
        b"Legajo;Periodo;Tipo;Cantidad;Importe\n1;202601;adelanto;1;-1500,50\n"
    )
    preview = analyze_file(BytesIO(content), "novelties")
    assert all(w.code != "formula_riesgosa" for w in preview.warnings)
    assert preview.errors == []


def test_v2_13_xss_en_nombre_se_rechaza() -> None:
    content = _employees_csv(
        ['1;<script>alert(1)</script>;Juan;20-12345678-6;15/03/2024']
    )
    preview = analyze_file(BytesIO(content), "employees")
    assert preview.valid_rows == []
    assert any(
        e.code == "caracteres_no_permitidos" and e.field == "apellido"
        for e in preview.errors
    )


def test_v2_13_xss_en_observacion_novedad_se_rechaza() -> None:
    content = (
        b"Legajo;Periodo;Tipo;Cantidad;Importe;Observacion\n"
        b"1;202601;horas_extra;2;100,00;<img src=x onerror=alert(1)>\n"
    )
    preview = analyze_file(BytesIO(content), "novelties")
    assert preview.valid_rows == []
    assert any(
        e.code == "caracteres_no_permitidos" and e.field == "observacion"
        for e in preview.errors
    )


def test_b47p_cuil_invalido_exige_11_digitos() -> None:
    content = _employees_csv(
        ["1;Pérez;Juan;20-12345678-7;15/03/2024"]
    )
    preview = analyze_file(BytesIO(content), "employees")
    assert len(preview.errors) == 1
    error = preview.errors[0]
    assert error.code == "cuil_invalido"
    assert "11" in error.message
    assert VALID_CUIL in error.message or "20-12345678-6" in error.message


def test_b47p_columna_faltante_cita_cabecera_valida() -> None:
    content = (
        "Legajo;Apellido;Nombre;Fecha de ingreso\n1;Pérez;Juan;15/03/2024\n"
    ).encode()
    preview = analyze_file(BytesIO(content), "employees")
    assert preview.missing_columns == ["cuil"]
    assert any(
        e.code == "columna_faltante" and "Cabecera valida" in e.message
        for e in preview.errors
    )
