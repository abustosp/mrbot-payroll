"""Validation tests: DSL, sources, dependencies, vigencia and tests."""

from __future__ import annotations

import sys
import types
from datetime import date

from app.ai.schemas import ProposalStatus
from app.ai.validation import validate_formula_proposal, validate_proposal


def _base(analysis):
    return analysis.formulas[0]


def test_valid_formula_passes_all_structural_checks(analysis, fixed_now):
    report = validate_formula_proposal(
        _base(analysis), analysis=analysis, now=fixed_now
    )
    assert report.is_valid is True
    assert report.errors == []
    assert report.formula_code == "ANTIGUEDAD"
    assert report.validator_version == "1.0"
    assert set(
        [
            "schema",
            "source_traceability",
            "formula_dsl",
            "dependencies",
            "validity_period",
            "suggested_tests",
        ]
    ).issubset(report.checks)
    assert report.validated_at == fixed_now
    if report.engine_validator is None:
        assert any("Structural DSL validation only" in item for item in report.limitations)


def test_unknown_operator_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={
            "formula": {
                "operator": "eval",
                "arguments": [{"constant": "1"}],
            }
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is False
    assert any(issue.code == "unknown_operator" for issue in report.errors)


def test_python_key_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={
            "formula": {
                "operator": "add",
                "arguments": [
                    {"variable": "sueldo_basico", "python": "os.system('x')"},
                    {"constant": "1"},
                ],
            }
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is False
    assert any(issue.code == "unsafe_expression" for issue in report.errors)


def test_nested_unknown_operator_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={
            "formula": {
                "operator": "add",
                "arguments": [
                    {"variable": "sueldo_basico"},
                    {"operator": "power", "arguments": [{"constant": "2"}]},
                ],
            }
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "unknown_operator" for issue in report.errors)


def test_binary_float_constant_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={
            "formula": {
                "operator": "add",
                "arguments": [
                    {"constant": 0.01},
                    {"constant": "1"},
                ],
            }
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "invalid_constant" for issue in report.errors)


def test_missing_content_hash_is_rejected(analysis):
    source = _base(analysis).source.model_copy(update={"content_hash": None})
    formula = _base(analysis).model_copy(update={"source": source})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is False
    assert any(issue.code == "missing_content_hash" for issue in report.errors)


def test_source_document_mismatch_is_rejected(analysis):
    source = _base(analysis).source.model_copy(update={"document_id": "otro"})
    formula = _base(analysis).model_copy(update={"source": source})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "source_document_mismatch" for issue in report.errors)


def test_unknown_dependency_is_rejected(analysis):
    formula = _base(analysis).model_copy(update={"depends_on": ["NO_EXISTE"]})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is False
    assert any(issue.code == "unknown_dependency" for issue in report.errors)


def test_self_dependency_is_rejected(analysis):
    formula = _base(analysis).model_copy(update={"depends_on": ["ANTIGUEDAD"]})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "dependency_cycle" for issue in report.errors)


def test_concept_self_reference_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={"formula": {"concept": "ANTIGUEDAD"}, "variables": []}
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "dependency_cycle" for issue in report.errors)


def test_circular_dependency_is_detected(analysis):
    first = _base(analysis).model_copy(
        update={"code": "FORMULA_A", "depends_on": ["FORMULA_B"]}
    )
    second = _base(analysis).model_copy(
        update={"code": "FORMULA_B", "depends_on": ["FORMULA_A"]}
    )
    modified = analysis.model_copy(update={"formulas": [first, second]})
    report = validate_formula_proposal(first, analysis=modified)
    assert report.is_valid is False
    assert any(issue.code == "dependency_cycle" for issue in report.errors)


def test_undeclared_variable_is_rejected(analysis):
    formula = _base(analysis).model_copy(update={"variables": ["sueldo_basico"]})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "undeclared_variable" for issue in report.errors)


def test_supplied_variable_catalog_rejects_unknown_variable(analysis):
    report = validate_formula_proposal(
        _base(analysis),
        analysis=analysis,
        known_variables={"sueldo_basico"},
    )
    assert any(issue.code == "unknown_variable" for issue in report.errors)


def test_invalid_validity_period_is_an_error(analysis):
    formula = _base(analysis).model_copy(
        update={"effective_to": date(2025, 1, 1)}
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(
        issue.code == "invalid_validity_period" for issue in report.errors
    )


def test_unknown_parameter_is_rejected_when_analysis_is_present(analysis):
    formula = _base(analysis).model_copy(
        update={
            "formula": {
                "operator": "add",
                "arguments": [
                    {"parameter": "NO_EXISTE"},
                    {"constant": "1"},
                ],
            }
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "unknown_parameter" for issue in report.errors)


def test_unknown_condition_operator_is_rejected(analysis):
    formula = _base(analysis).model_copy(
        update={
            "conditions": [
                {"field": "x", "operator": "execute", "value": 1}
            ]
        }
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "invalid_condition" for issue in report.errors)


def test_missing_tests_is_only_a_warning(analysis):
    formula = _base(analysis).model_copy(update={"tests": []})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is True
    assert any(issue.code == "missing_tests" for issue in report.warnings)


def test_test_period_outside_validity_is_flagged(analysis):
    test = _base(analysis).tests[0].model_copy(update={"period": date(2025, 6, 1)})
    formula = _base(analysis).model_copy(update={"tests": [test]})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(
        issue.code == "test_period_outside_validity" for issue in report.warnings
    )


def test_formula_before_agreement_is_flagged(analysis):
    formula = _base(analysis).model_copy(
        update={"effective_from": date(2025, 12, 1)}
    )
    report = validate_formula_proposal(formula, analysis=analysis)
    assert any(issue.code == "formula_before_agreement" for issue in report.warnings)


def test_source_without_page_or_article_is_flagged(analysis):
    source = _base(analysis).source.model_copy(update={"page": None, "article": None})
    formula = _base(analysis).model_copy(update={"source": source})
    report = validate_formula_proposal(formula, analysis=analysis)
    assert report.is_valid is True
    assert any(issue.code == "source_not_specific" for issue in report.warnings)


def test_validate_proposal_transitions_draft_to_validated(analysis):
    proposal = _base(analysis)
    assert proposal.status is ProposalStatus.DRAFT
    validated = validate_proposal(proposal, analysis=analysis)
    assert validated.status is ProposalStatus.VALIDATED
    assert validated.validation is not None
    assert validated.validation.is_valid is True
    assert proposal.status is ProposalStatus.DRAFT


def test_validate_proposal_keeps_invalid_in_draft(analysis):
    formula = _base(analysis).model_copy(
        update={"formula": {"operator": "eval", "arguments": []}}
    )
    validated = validate_proposal(formula, analysis=analysis)
    assert validated.status is ProposalStatus.DRAFT
    assert validated.validation is not None
    assert validated.validation.is_valid is False


def test_engine_validator_is_used_when_available(monkeypatch, analysis):
    module = types.ModuleType("app.core.payroll_engine.validations")
    module.validate_formula = lambda definition: True  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.payroll_engine.validations", module)
    report = validate_formula_proposal(_base(analysis), analysis=analysis)
    assert report.engine_validator == (
        "app.core.payroll_engine.validations.validate_formula"
    )
    assert report.is_valid is True
    assert "engine_formula_validator" in report.checks


def test_engine_validator_rejection_blocks_validity(monkeypatch, analysis):
    module = types.ModuleType("app.core.payroll_engine.validations")
    module.validate_formula = lambda definition: ["division by zero"]  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.payroll_engine.validations", module)
    report = validate_formula_proposal(_base(analysis), analysis=analysis)
    assert report.is_valid is False
    assert any(
        issue.code == "engine_validation_failed" for issue in report.errors
    )


def test_engine_validator_exception_blocks_validity(monkeypatch, analysis):
    def reject(definition):
        raise ValueError("unknown parameter in engine catalog")

    module = types.ModuleType("app.core.payroll_engine.validations")
    module.validate_formula = reject  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.payroll_engine.validations", module)
    report = validate_formula_proposal(_base(analysis), analysis=analysis)
    assert report.is_valid is False
    assert any(
        issue.code == "engine_validation_failed" for issue in report.errors
    )


def test_engine_validator_incompatible_signature_is_a_limitation(
    monkeypatch, analysis
):
    def incompatible(definition, context):  # noqa: ANN001
        return True

    module = types.ModuleType("app.core.payroll_engine.validations")
    module.validate_formula = incompatible  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "app.core.payroll_engine.validations", module)
    report = validate_formula_proposal(_base(analysis), analysis=analysis)
    assert report.is_valid is True
    assert any("signature is incompatible" in item for item in report.limitations)


def test_formula_round_trip_to_engine_contract_is_draft(analysis):
    definition = _base(analysis).to_formula_definition()
    assert definition.status.value == "DRAFT"
    assert definition.code == "ANTIGUEDAD"
