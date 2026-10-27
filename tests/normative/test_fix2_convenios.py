"""Validaciones mínimas fix2-convenios (V2-04/05/15/16/17/18/19 + B-19P/20P/37R/38R)."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.core.payroll_engine.formula_engine import evaluate_formula
from app.core.payroll_engine.types import FormulaContext, FormulaDefinition

ROOT = Path(__file__).resolve().parents[2]
CCT_DIR = ROOT / "normative" / "cct"
CATALOG_PATH = CCT_DIR / "catalog.json"
FORMULAS_PATH = CCT_DIR / "formulas.json"


def _load_formulas() -> dict[str, dict]:
    data = json.loads(FORMULAS_PATH.read_text(encoding="utf-8"))
    return {item["code"]: item for item in data}


def _eval(code: str, *, variables=None, parameters=None, concepts=None) -> Decimal:
    item = _load_formulas()[code]
    definition = FormulaDefinition.model_validate(item)
    ctx = FormulaContext(
        variables=variables or {},
        parameters=parameters or {},
        concepts=concepts or {},
    )
    return evaluate_formula(definition, ctx).value


def test_v2_04_complemento_12_y_cita() -> None:
    formulas = _load_formulas()
    asistencia = formulas["CCT_389_04_ASISTENCIA"]
    assert "11.5" in asistencia["source"] and "11.4" in asistencia["source"]
    complemento = formulas["CCT_389_04_COMPLEMENTO_SERVICIO"]
    assert complemento["nature"] == "REMUNERATIVE"
    assert "11.6" in complemento["source"] and "12%" in complemento["description"]
    assert _eval(
        "CCT_389_04_COMPLEMENTO_SERVICIO",
        parameters={"cct38904_porcentaje_complemento": "0.12"},
        concepts={"SUELDO_BASICO": "700000.00"},
    ) == Decimal("84000.00")
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cct = next(c for c in catalog if c["code"] == "389/04")
    assert "CCT_389_04_COMPLEMENTO_SERVICIO" in cct["formula_codes"]


def test_v2_05_nr_150k_ventana_unica() -> None:
    item = _load_formulas()["CCT_244_94_SUMA_EXTRAORDINARIA_NR"]
    assert item["nature"] == "NON_REMUNERATIVE"
    assert item["valid_from"] == "2026-10-22" and item["valid_to"] == "2026-11-15"
    assert "150.000" in item["source"] and "EX-2026-46512333" in item["source"]
    assert _eval(
        "CCT_244_94_SUMA_EXTRAORDINARIA_NR",
        parameters={"cct24494_suma_extraordinaria_nr": "150000.00"},
    ) == Decimal("150000.00")


def test_v2_15_presentismo_hasta_1_ausencia() -> None:
    item = _load_formulas()["CCT_130_75_PRESENTISMO"]
    assert len(item["conditions"]) == 1
    cond = item["conditions"][0]
    assert cond["field"] == "dias_ausentes" and cond["value"] == 1
    assert cond["operator"] in {"lte", "less_than_or_equal", "less_than_or_equal_to"}
    base = {"SUELDO_BASICO": "1200000.00", "CCT_130_75_ANTIGUEDAD": "0.00"}
    assert _eval("CCT_130_75_PRESENTISMO", variables={"dias_ausentes": 0}, concepts=base) == Decimal(
        "100000.00"
    )
    assert _eval("CCT_130_75_PRESENTISMO", variables={"dias_ausentes": 1}, concepts=base) == Decimal(
        "100000.00"
    )
    assert _eval("CCT_130_75_PRESENTISMO", variables={"dias_ausentes": 2}, concepts=base) == Decimal(
        "0.00"
    )


def test_v2_16_nr_mensual_y_dia_sanidad() -> None:
    formulas = _load_formulas()
    nr = formulas["CCT_122_75_SUMA_NR_MENSUAL"]
    assert nr["nature"] == "NON_REMUNERATIVE"
    assert nr["valid_from"] == "2026-09-01" and nr["valid_to"] == "2027-01-31"
    assert "$80.000" in nr["source"] or "80.000" in nr["source"]
    assert _eval(
        "CCT_122_75_SUMA_NR_MENSUAL",
        parameters={"cct12275_suma_nr_mensual": "80000.00"},
    ) == Decimal("80000.00")
    dia = formulas["CCT_122_75_DIA_SANIDAD"]
    assert dia["valid_from"] == "2026-09-01" and dia["valid_to"] == "2026-09-20"
    assert "70.304,21" in dia["source"] or "70304" in dia["source"].replace(".", "")
    assert _eval(
        "CCT_122_75_DIA_SANIDAD",
        parameters={"cct12275_dia_sanidad": "70304.21"},
    ) == Decimal("70304.21")


def test_v2_17_presentismo_y_viatico_507() -> None:
    formulas = _load_formulas()
    pres = formulas["CCT_507_07_PRESENTISMO"]
    assert pres["nature"] == "REMUNERATIVE"
    assert pres["valid_from"] == "2026-07-01" and pres["valid_to"] == "2026-12-31"
    assert "180.000" in pres["source"] or "180000" in pres["source"]
    assert _eval(
        "CCT_507_07_PRESENTISMO",
        variables={"asistencia_perfecta_mes": 1},
        parameters={"cct50707_presentismo_mensual": "180000.00"},
    ) == Decimal("180000.00")
    viat = formulas["CCT_507_07_VIATICO"]
    assert viat["nature"] == "NON_REMUNERATIVE"
    assert "20.220" in viat["source"] or "20220" in viat["source"]
    assert _eval(
        "CCT_507_07_VIATICO",
        variables={"dias_trabajados": 25},
        parameters={"cct50707_viatico_diario": "20220.00"},
    ) == Decimal("505500.00")


def test_v2_18_subconjunto_con_advertencia() -> None:
    scales = json.loads((CCT_DIR / "evidence" / "cct_18_75" / "scales.json").read_text())
    verified = [s for s in scales["scales"] if s["status"] == "verified"]
    unverified = [s for s in scales["scales"] if s["status"] != "verified"]
    assert len(verified) == 17 and len(unverified) == 2
    assert any("OCR" in s.get("notes", "") for s in unverified)
    notes = (CCT_DIR / "evidence" / "cct_18_75" / "notes.md").read_text(encoding="utf-8")
    assert "ADVERTENCIA" in notes and "sin cobertura verificada" in notes
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cct = next(c for c in catalog if c["code"] == "18/75")
    assert len(cct["salary_scales"]) == 17


def test_v2_19_divisor_200_citado() -> None:
    formulas = _load_formulas()
    for code in ("STD_HORAS_EXTRA_50", "STD_HORAS_EXTRA_100"):
        item = formulas[code]
        assert "/ 200" in item["description"] or "/200" in item["description"]
        assert "200 h" in item["source"] and "P_HORAS_MES" in item["source"]
        assert "200 horas mensuales" in item["source"]


def test_b19p_cotejo_documentado() -> None:
    notes = (CCT_DIR / "evidence" / "cct_589_10" / "notes.md").read_text(encoding="utf-8")
    assert "Profundización B-19P" in notes and "88 filas" in notes
    scales = json.loads((CCT_DIR / "evidence" / "cct_589_10" / "scales.json").read_text())
    assert len(scales["scales"]) == 48
    assert all(s["confidence"] == "medium" for s in scales["scales"])
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cct = next(c for c in catalog if c["code"] == "589/10")
    assert len(cct["salary_scales"]) == 48


def test_b20p_segundo_tramo_documentado_no_cargado() -> None:
    notes = (CCT_DIR / "evidence" / "cct_389_04" / "notes.md").read_text(encoding="utf-8")
    assert "Profundización B-20P" in notes and "sin correlato" in notes
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cct = next(c for c in catalog if c["code"] == "389/04")
    assert len(cct["salary_scales"]) == 22
    assert cct["latest_verified_to"] == "2026-09-30"


def test_b37r_serie_2020_2023_reconciliada() -> None:
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    by_code = {c["code"]: c for c in catalog}
    for code in ("130/75", "122/75", "260/75", "76/75"):
        years = {s["vigencia_desde"][:4] for s in by_code[code]["salary_scales"]}
        assert {"2020", "2021", "2022", "2023"} <= years, (code, sorted(years))
    cct244 = by_code["244/94"]
    years244 = {s["vigencia_desde"][:4] for s in cct244["salary_scales"]}
    assert {"2020", "2021", "2022"} <= years244
    assert "2023" not in years244  # ausente en ambas fuentes, documentado en README


def test_b38r_basicos_imposibles_fuera_de_catalogo() -> None:
    scales = json.loads((CCT_DIR / "evidence" / "cct_264_95" / "scales.json").read_text())
    verified = [s for s in scales["scales"] if s["status"] == "verified"]
    unverified = [s for s in scales["scales"] if s["status"] != "verified"]
    assert len(verified) == 30 and len(unverified) == 2
    assert all(s["amount"] is None for s in unverified)
    notes = (CCT_DIR / "evidence" / "cct_264_95" / "notes.md").read_text(encoding="utf-8")
    assert "Confirmación de imposibilidad B-38R" in notes
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    cct = next(c for c in catalog if c["code"] == "264/95")
    assert len(cct["salary_scales"]) == 30
    assert all(s["importe"] is not None for s in cct["salary_scales"])
