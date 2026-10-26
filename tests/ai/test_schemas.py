"""Schema-level tests: strictness, aliases and draft-only conversion."""

from __future__ import annotations

from datetime import date

import pytest
from pydantic import ValidationError

from app.ai.schemas import (
    AgreementAnalysis,
    DocumentMetadata,
    ProposalStatus,
    ProposedFormula,
    SourceReference,
)
from app.core.payroll_engine.types import FormulaStatus


def _formula_payload(source: dict) -> dict:
    return {
        "code": "ANTIGUEDAD",
        "description": "Adicional por antiguedad",
        "formula": {
            "operator": "multiply",
            "arguments": [
                {"variable": "sueldo_basico"},
                {"parameter": "PORCENTAJE_ANTIGUEDAD"},
            ],
        },
        "variables": ["sueldo_basico"],
        "source": source,
        "effective_from": "2026-01-01",
        "tests": [],
    }


def test_source_accepts_document_version_alias():
    source = SourceReference.model_validate(
        {"document_id": "cct", "document_version": "2026-10", "page": 1}
    )
    assert source.version == "2026-10"


def test_source_rejects_blank_identity():
    with pytest.raises(ValidationError):
        SourceReference(document_id="   ", version="1")


def test_source_rejects_invalid_content_hash():
    with pytest.raises(ValidationError):
        SourceReference(
            document_id="cct",
            version="1",
            content_hash="not-a-sha256",
        )


def test_missing_source_is_rejected():
    payload = _formula_payload(source={"document_id": "cct", "version": "1"})
    payload.pop("source")
    with pytest.raises(ValidationError) as excinfo:
        ProposedFormula.model_validate(payload)
    assert "source" in str(excinfo.value)


def test_extra_fields_are_rejected():
    payload = _formula_payload(source={"document_id": "cct", "version": "1"})
    payload["unexpected"] = True
    with pytest.raises(ValidationError):
        ProposedFormula.model_validate(payload)


def test_effective_range_is_validated():
    payload = _formula_payload(source={"document_id": "cct", "version": "1"})
    payload["effective_to"] = "2025-12-01"
    with pytest.raises(ValidationError):
        ProposedFormula.model_validate(payload)


def test_approved_status_requires_approved_by():
    payload = _formula_payload(source={"document_id": "cct", "version": "1"})
    payload["status"] = "approved"
    with pytest.raises(ValidationError):
        ProposedFormula.model_validate(payload)


def test_formula_definition_conversion_is_always_draft():
    payload = _formula_payload(
        source={
            "document_id": "cct",
            "version": "1",
            "content_hash": "sha256:" + "a" * 64,
        }
    )
    payload.update(
        {
            "status": "approved",
            "approved_by": "user_15",
            "effective_to": "2026-12-31",
        }
    )
    proposal = ProposedFormula.model_validate(payload)
    definition = proposal.to_formula_definition()
    assert definition.status is FormulaStatus.DRAFT
    assert definition.code == "ANTIGUEDAD"
    assert definition.source.startswith("cct@1")


def test_parameter_rejects_nan():
    with pytest.raises(ValidationError):
        from app.ai.schemas import ProposedParameter

        ProposedParameter.model_validate(
            {
                "code": "P",
                "name": "P",
                "value": "NaN",
                "source": {"document_id": "cct", "version": "1"},
            }
        )


def test_parameter_accepts_json_number_and_stores_decimal():
    from decimal import Decimal

    from app.ai.schemas import ProposedParameter

    parameter = ProposedParameter.model_validate(
        {
            "code": "P",
            "name": "P",
            "value": 0.01,
            "source": {"document_id": "cct", "version": "1"},
        }
    )
    assert parameter.value == Decimal("0.01")
    assert isinstance(parameter.value, Decimal)


def test_analysis_rejects_duplicate_formula_codes(metadata, payload):
    payload["formulas"].append(dict(payload["formulas"][0]))
    payload["document"] = metadata.model_dump(mode="json")
    payload["analyzed_at"] = "2026-10-26T12:00:00+00:00"
    with pytest.raises(ValidationError) as excinfo:
        AgreementAnalysis.model_validate(payload)
    assert "duplicate formula" in str(excinfo.value)


def test_document_metadata_trims_identity():
    metadata = DocumentMetadata(document_id="  cct  ", version=" 1 ")
    assert metadata.document_id == "cct"
    assert metadata.version == "1"


def test_proposal_status_values_are_lowercase():
    assert {status.value for status in ProposalStatus} == {
        "draft",
        "validated",
        "approved",
        "rejected",
    }


def test_date_type_is_preserved(metadata):
    assert isinstance(date(2026, 1, 1), date)
    assert metadata.document_id
