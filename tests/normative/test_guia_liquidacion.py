"""Oraculo guia de liquidacion (Comercio marzo-2020) + matriz por convenio.

Guia: /home/abp/Downloads/920015926-Liquidacion-de-Sueldos.pdf, pp. 47-48.
Caso: Pablo Suligoy, Vendedor A, ingreso 12/10/2000, basico 34308.14,
antiguedad 19 anios -> 6518.55, presentismo (bas+ant)/12 -> 3402.22,
hora conformada (bas+ant+pres)/200 -> 221.14, NR 1000.
4 HS50 -> 1326.84, 2 HS100 -> 884.56, bruto -> 46440.31.
"""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path

from app.core.payroll_engine.formula_engine import evaluate_formula
from app.core.payroll_engine.types import FormulaContext, FormulaDefinition

ROOT = Path(__file__).resolve().parents[2]
FORMULAS_PATH = ROOT / "normative" / "cct" / "formulas.json"
CATALOG_PATH = ROOT / "normative" / "cct" / "catalog.json"

BASICO = Decimal("34308.14")
ANTIGUEDAD = Decimal("6518.55")
PRESENTISMO = Decimal("3402.22")
HORA_CONFORMADA = Decimal("221.14")


def _load() -> dict[str, dict]:
    data = json.loads(FORMULAS_PATH.read_text(encoding="utf-8"))
    return {item["code"]: item for item in data}


def _eval(code: str, *, variables=None, parameters=None, concepts=None) -> Decimal:
    item = _load()[code]
    definition = FormulaDefinition.model_validate(item)
    ctx = FormulaContext(
        variables=variables or {},
        parameters=parameters or {},
        concepts=concepts or {},
    )
    return evaluate_formula(definition, ctx).value


def test_oraculo_antiguedad_19_anios() -> None:
    assert _eval(
        "CCT_130_75_ANTIGUEDAD",
        variables={"anios_antiguedad": 19},
        parameters={"cct13075_porcentaje_antiguedad": "0.01"},
        concepts={"SUELDO_BASICO": "34308.14"},
    ) == ANTIGUEDAD


def test_oraculo_presentismo_guia_sin_nr() -> None:
    # Guia: (basico + antiguedad) / 12, con NR 0 la base ampliada coincide.
    assert _eval(
        "CCT_130_75_PRESENTISMO",
        variables={"dias_ausentes": 0},
        concepts={
            "SUELDO_BASICO": "34308.14",
            "CCT_130_75_ANTIGUEDAD": "6518.55",
            "CCT_130_75_SUMA_NR_MENSUAL": "0.00",
        },
    ) == PRESENTISMO


def test_oraculo_hora_conformada_y_bruto() -> None:
    hora = _eval(
        "CCT_130_75_HORA_CONFORMADA",
        concepts={
            "SUELDO_BASICO": "34308.14",
            "CCT_130_75_ANTIGUEDAD": "6518.55",
            "CCT_130_75_PRESENTISMO": "3402.22",
        },
    )
    assert hora == HORA_CONFORMADA
    he50 = _eval(
        "CCT_130_75_HORA_EXTRA_50",
        variables={"horas_extra_50_cantidad": 4},
        concepts={"CCT_130_75_HORA_CONFORMADA": "221.14"},
    )
    he100 = _eval(
        "CCT_130_75_HORA_EXTRA_100",
        variables={"horas_extra_100_cantidad": 2},
        concepts={"CCT_130_75_HORA_CONFORMADA": "221.14"},
    )
    assert he50 == Decimal("1326.84")
    assert he100 == Decimal("884.56")
    bruto_remunerativo = BASICO + ANTIGUEDAD + PRESENTISMO + he50 + he100
    assert bruto_remunerativo == Decimal("46440.31")
    # Suma NR mensual aparte (no integra la base de aportes del oraculo guia).
    assert bruto_remunerativo + Decimal("1000.00") == Decimal("47440.31")


def test_presentismo_base_ampliada_rige_desde_acuerdo_07_2026() -> None:
    # La guia (oraculo 2020) usa (basico + antiguedad) / 12; la base con NR
    # rige desde los haberes de julio 2026 (Acuerdo 07/2026).
    item = _load()["CCT_130_75_PRESENTISMO"]
    assert item["valid_from"] == "2026-07-01"
    assert "07/2026" in item["source"] or "07-2026" in item["source"]


def test_matriz_once_cct_con_formula_verde() -> None:
    formulas = _load()
    catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    assert len(catalog) == 11
    por_cct = {
        "130/75": "CCT_130_75_ANTIGUEDAD",
        "260/75": "CCT_260_75_ANTIGUEDAD",
        "76/75": "CCT_76_75_ASISTENCIA",
        "18/75": "CCT_18_75_FALLA_CAJA",
        "40/89": "CCT_40_89_ANTIGUEDAD",
        "389/04": "CCT_389_04_COMPLEMENTO_SERVICIO",
        "122/75": "CCT_122_75_ESCALAFON",
        "264/95": "CCT_264_95_FALLA_CAJA",
        "244/94": "CCT_244_94_ANTIGUEDAD",
        "507/07": "CCT_507_07_ANTIGUEDAD",
        "589/10": "CCT_589_10_ANTIGUEDAD",
    }
    for cct in catalog:
        code = por_cct[cct["code"]]
        assert code in formulas, f"{cct['code']} sin formula {code}"
        assert code in cct["formula_codes"], f"{cct['code']} no lista {code}"
        item = formulas[code]
        assert item["status"] == "APPROVED"
        first = item["tests"][0]
        assert _eval(
            code,
            variables=first.get("variables", {}),
            parameters=first.get("parameters", {}),
            concepts=first.get("concepts", {}),
        ) == Decimal(str(first["expected"]))
