from decimal import Decimal

import pytest

from app.ai.scales import parse_scales, sanitize_category_code
from app.ai.schemas import DocumentMetadata


def test_parse_scales_produces_draft_formulas_with_exact_amounts():
    rows = [
        {"category_code": "vigilador general", "amount": "1085000.00", "valid_from": "2026-12-01", "valid_to": "2026-12-31", "source_table": "ESCALA DICIEMBRE"},
        {"category_code": "vigilador-bombero", "amount": "1159500.05", "valid_from": "2026-12-01", "valid_to": "2026-12-31", "source_table": "ESCALA DICIEMBRE"},
        {"category_code": "invalida", "amount": "no decimal", "valid_from": "2026-12-01"},
    ]
    parameters, formulas, skipped = parse_scales(rows, {"document_id": "doc", "version": "1"})

    assert len(parameters) == len(formulas) == 2
    assert len(skipped) == 1 and "amount" in skipped[0]
    for parameter, formula, category, amount in zip(
        parameters,
        formulas,
        ("VIGILADOR_GENERAL", "VIGILADOR_BOMBERO"),
        ("1085000.00", "1159500.05"),
        strict=True,
    ):
        code = f"SUELDO_BASICO_{category}"
        assert parameter.code == formula.code == code
        assert parameter.model_dump(mode="json")["value"] == amount
        assert parameter.unit == "currency"
        assert formula.formula == {"parameter": code}
        assert formula.status == "draft"
        assert formula.nature == "REMUNERATIVE"
        assert formula.tests[0].inputs == {}
        assert formula.tests[0].model_dump(mode="json")["expected"] == amount
        assert formula.tests[0].expected == Decimal(amount)
        assert parameter.source == formula.source
        assert parameter.source.content_hash.startswith("sha256:")
        assert parameter.source.document_id == "doc"
        assert parameter.source.version == "1"
        assert parameter.source.article == "ESCALA DICIEMBRE"
        assert parameter.effective_from == formula.effective_from
        assert parameter.effective_to == formula.effective_to
        assert str(formula.effective_from) == "2026-12-01"
        assert str(formula.effective_to) == "2026-12-31"


@pytest.mark.parametrize("changes, reason", [
    ({"category_code": ""}, "category_code"),
    ({"category_code": "---"}, "category_code"),
    ({"amount": "0"}, "amount"),
    ({"amount": "NaN"}, "amount"),
    ({"amount": 1.5}, "amount"),
    ({"valid_from": "2027-01-01"}, "effective_to"),
    ({"valid_from": "invalid"}, "effective_from"),
    ({"valid_from": None}, "effective_from"),
])
def test_invalid_rows_are_skipped(changes, reason):
    row = {"category_code": "A", "amount": "10.00", "valid_from": "2026-01-01", "valid_to": "2026-12-31"}
    row.update(changes)
    parameters, formulas, skipped = parse_scales([row], DocumentMetadata(document_id="doc", version="1"))
    assert parameters == formulas == []
    assert len(skipped) == 1 and reason in skipped[0]


def test_sanitize_category_code():
    assert sanitize_category_code("cat-a / 2") == "CAT_A___2"
