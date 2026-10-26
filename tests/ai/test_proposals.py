"""Proposal lifecycle tests: draft-only, human approval, no publication."""

from __future__ import annotations

import pytest

from app.ai.errors import ApprovalError, ProposalError
from app.ai.proposals import (
    approve_proposal,
    propose_all,
    propose_formula,
    reject_proposal,
)
from app.ai.schemas import ProposalStatus
from app.ai.validation import validate_proposal


def _validated(analysis, now):
    draft = propose_formula(analysis, "ANTIGUEDAD", now=now)
    return validate_proposal(draft, analysis=analysis, now=now)


def test_mock_flow_produces_draft_with_source_and_validation(analysis, fixed_now):
    proposal = propose_formula(analysis, "ANTIGUEDAD", now=fixed_now)
    assert proposal.status is ProposalStatus.DRAFT
    assert proposal.source.content_hash == analysis.document.content_hash
    assert proposal.source.page == 12
    assert proposal.validation is not None
    assert proposal.validation.is_valid is True
    assert proposal.approved_by is None
    assert analysis.formulas[0].status is ProposalStatus.DRAFT


def test_unknown_formula_code_fails(analysis):
    with pytest.raises(ProposalError, match="not found"):
        propose_formula(analysis, "NO_EXISTE")


def test_propose_all_returns_drafts(analysis, fixed_now):
    proposals = propose_all(analysis, now=fixed_now)
    assert len(proposals) == 1
    assert proposals[0].status is ProposalStatus.DRAFT


def test_approval_without_user_fails(analysis, fixed_now):
    validated = _validated(analysis, fixed_now)
    with pytest.raises(ApprovalError, match="approved_by is required"):
        approve_proposal(validated, "   ")
    with pytest.raises(ApprovalError, match="approved_by is required"):
        approve_proposal(validated, None)  # type: ignore[arg-type]


def test_approval_from_draft_fails(analysis, fixed_now):
    draft = propose_formula(analysis, "ANTIGUEDAD", now=fixed_now)
    with pytest.raises(ApprovalError, match="validated"):
        approve_proposal(draft, "user_15")


def test_approval_requires_a_validation_report(analysis, fixed_now):
    validated = _validated(analysis, fixed_now).model_copy(
        update={"validation": None}
    )
    with pytest.raises(ApprovalError, match="ValidationReport"):
        approve_proposal(validated, "user_15")


def test_validated_proposal_can_be_approved_without_mutating_input(
    analysis, fixed_now
):
    validated = _validated(analysis, fixed_now)
    approved = approve_proposal(
        validated, "  user_15  ", analysis=analysis, now=fixed_now
    )
    assert approved.status is ProposalStatus.APPROVED
    assert approved.approved_by == "user_15"
    assert approved.approved_at == fixed_now
    assert approved.validation is not None and approved.validation.is_valid
    assert validated.status is ProposalStatus.VALIDATED
    assert validated.approved_by is None
    assert analysis.formulas[0].status is ProposalStatus.DRAFT


def test_approved_formula_definition_stays_draft(analysis, fixed_now):
    approved = approve_proposal(
        _validated(analysis, fixed_now), "user_15", analysis=analysis
    )
    definition = approved.to_formula_definition()
    assert approved.status is ProposalStatus.APPROVED
    assert definition.status.value == "DRAFT"


def test_approval_fails_if_formula_was_tampered_after_validation(
    analysis, fixed_now
):
    validated = _validated(analysis, fixed_now)
    validated.formula["operator"] = "eval"
    with pytest.raises(ApprovalError, match="re-validation"):
        approve_proposal(validated, "user_15", analysis=analysis)


def test_approval_fails_if_stored_report_is_not_valid(analysis, fixed_now):
    validated = _validated(analysis, fixed_now)
    broken = validated.validation.model_copy(update={"is_valid": False})  # type: ignore[union-attr]
    tampered = validated.model_copy(update={"validation": broken})
    with pytest.raises(ApprovalError, match="validation errors"):
        approve_proposal(tampered, "user_15", analysis=analysis)


def test_approved_proposal_cannot_be_approved_twice(analysis, fixed_now):
    approved = approve_proposal(
        _validated(analysis, fixed_now), "user_15", analysis=analysis
    )
    with pytest.raises(ApprovalError, match="already approved"):
        approve_proposal(approved, "user_16", analysis=analysis)


def test_reject_preserves_reviewer_and_blocks_approval(analysis, fixed_now):
    validated = _validated(analysis, fixed_now)
    rejected = reject_proposal(
        validated, "reviewer_2", "Falta la escala salarial", now=fixed_now
    )
    assert rejected.status is ProposalStatus.REJECTED
    assert rejected.rejected_by == "reviewer_2"
    assert rejected.rejected_at == fixed_now
    assert rejected.rejection_reason == "Falta la escala salarial"
    assert rejected.approved_by is None
    with pytest.raises(ApprovalError, match="rejected"):
        approve_proposal(rejected, "user_15")


def test_reject_requires_reviewer_and_reason(analysis, fixed_now):
    validated = _validated(analysis, fixed_now)
    with pytest.raises(ProposalError, match="rejected_by"):
        reject_proposal(validated, "  ", "motivo")
    with pytest.raises(ProposalError, match="reason"):
        reject_proposal(validated, "reviewer_2", "   ")


def test_approved_proposal_cannot_be_rejected(analysis, fixed_now):
    approved = approve_proposal(
        _validated(analysis, fixed_now), "user_15", analysis=analysis
    )
    with pytest.raises(ProposalError, match="cannot be rejected"):
        reject_proposal(approved, "reviewer_2", "cambio de opinion")


def test_invalid_formula_still_yields_draft_with_error_report(analysis, fixed_now):
    bad = analysis.formulas[0].model_copy(
        update={"formula": {"operator": "eval", "arguments": []}}
    )
    modified = analysis.model_copy(update={"formulas": [bad]})
    proposal = propose_formula(modified, "ANTIGUEDAD", now=fixed_now)
    assert proposal.status is ProposalStatus.DRAFT
    assert proposal.validation is not None
    assert proposal.validation.is_valid is False
    assert proposal.validation.errors
