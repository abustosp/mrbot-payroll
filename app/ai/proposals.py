"""Proposal lifecycle: draft -> validated -> approved/rejected.

Approval is a human review record only. Nothing in this module writes to the
payroll engine, publishes a rule or mutates an existing production definition.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from app.ai.errors import ApprovalError, ProposalError
from app.ai.schemas import (
    AgreementAnalysis,
    ProposalStatus,
    ProposedFormula,
)
from app.ai.validation import validate_formula_proposal


def _utcnow() -> datetime:
    return datetime.now(UTC)


def propose_formula(
    analysis: AgreementAnalysis,
    code: str,
    *,
    known_variables: Iterable[str] = (),
    known_parameters: Iterable[str] = (),
    known_concepts: Iterable[str] = (),
    now: datetime | None = None,
) -> ProposedFormula:
    """Build a draft proposal for one formula found in an analysis.

    The returned object always has ``status == "draft"``, an attached source and
    a fresh :class:`ValidationReport`. Invalid content yields a draft whose
    report has errors, so a reviewer can see exactly what needs fixing.
    """

    if not isinstance(analysis, AgreementAnalysis):
        raise ProposalError("propose_formula expects an AgreementAnalysis")
    if not isinstance(code, str) or not code.strip():
        raise ProposalError("formula code is required")

    formula = analysis.formula(code.strip())
    if formula is None:
        available = ", ".join(item.code for item in analysis.formulas) or "<none>"
        raise ProposalError(
            f"formula {code!r} was not found in the analysis; available: {available}"
        )

    proposal = formula.model_copy(
        update={
            "status": ProposalStatus.DRAFT,
            "approved_by": None,
            "approved_at": None,
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
        }
    )
    report = validate_formula_proposal(
        proposal,
        analysis=analysis,
        known_variables=known_variables,
        known_parameters=known_parameters,
        known_concepts=known_concepts,
        now=now,
    )
    return proposal.model_copy(update={"validation": report})


def approve_proposal(
    proposal: ProposedFormula,
    approved_by: str,
    *,
    analysis: AgreementAnalysis | None = None,
    known_variables: Iterable[str] = (),
    known_parameters: Iterable[str] = (),
    known_concepts: Iterable[str] = (),
    now: datetime | None = None,
) -> ProposedFormula:
    """Approve a *validated* proposal with an explicit human identifier.

    The function is pure: it returns a new object and never mutates production
    rules. ``approved_by`` is mandatory and cannot be supplied by the model.
    """

    if not isinstance(proposal, ProposedFormula):
        raise ApprovalError("approve_proposal expects a ProposedFormula")
    if not isinstance(approved_by, str) or not approved_by.strip():
        raise ApprovalError(
            "approved_by is required to approve a proposal; a named authorised "
            "user must be recorded"
        )
    if proposal.status is ProposalStatus.APPROVED:
        raise ApprovalError("proposal is already approved")
    if proposal.status is ProposalStatus.REJECTED:
        raise ApprovalError("a rejected proposal cannot be approved")
    if proposal.status is not ProposalStatus.VALIDATED:
        raise ApprovalError(
            "proposal must be in 'validated' state before approval; current state: "
            f"{proposal.status.value}"
        )
    if proposal.validation is None:
        raise ApprovalError("proposal has no ValidationReport")
    if not proposal.validation.is_valid:
        raise ApprovalError("proposal has validation errors and cannot be approved")

    report = proposal.validation
    if analysis is not None:
        report = validate_formula_proposal(
            proposal,
            analysis=analysis,
            known_variables=known_variables,
            known_parameters=known_parameters,
            known_concepts=known_concepts,
            now=now,
        )
        if not report.is_valid:
            details = "; ".join(issue.message for issue in report.errors)
            raise ApprovalError(
                f"proposal failed re-validation at approval time: {details}"
            )
    else:
        structural = validate_formula_proposal(
            proposal,
            known_variables=known_variables,
            known_parameters=known_parameters,
            known_concepts=known_concepts,
            now=now,
        )
        if not structural.is_valid:
            details = "; ".join(issue.message for issue in structural.errors)
            raise ApprovalError(
                f"proposal failed structural validation at approval time: {details}"
            )
        report = structural

    return proposal.model_copy(
        update={
            "status": ProposalStatus.APPROVED,
            "approved_by": approved_by.strip(),
            "approved_at": now or _utcnow(),
            "rejected_by": None,
            "rejected_at": None,
            "rejection_reason": None,
            "validation": report,
        }
    )


def reject_proposal(
    proposal: ProposedFormula,
    rejected_by: str,
    reason: str,
    *,
    now: datetime | None = None,
) -> ProposedFormula:
    """Reject a draft or validated proposal, preserving the review trail."""

    if not isinstance(proposal, ProposedFormula):
        raise ProposalError("reject_proposal expects a ProposedFormula")
    if not isinstance(rejected_by, str) or not rejected_by.strip():
        raise ProposalError("rejected_by is required to reject a proposal")
    if not isinstance(reason, str) or not reason.strip():
        raise ProposalError("rejection reason is required")
    if proposal.status is ProposalStatus.APPROVED:
        raise ProposalError("an approved proposal cannot be rejected")
    if proposal.status is ProposalStatus.REJECTED:
        raise ProposalError("proposal is already rejected")

    return proposal.model_copy(
        update={
            "status": ProposalStatus.REJECTED,
            "rejected_by": rejected_by.strip(),
            "rejected_at": now or _utcnow(),
            "rejection_reason": reason.strip(),
            "approved_by": None,
            "approved_at": None,
        },
    )


def propose_all(
    analysis: AgreementAnalysis,
    *,
    known_variables: Iterable[str] = (),
    known_parameters: Iterable[str] = (),
    known_concepts: Iterable[str] = (),
    now: datetime | None = None,
) -> list[ProposedFormula]:
    """Create draft proposals for every formula in an analysis."""

    return [
        propose_formula(
            analysis,
            formula.code,
            known_variables=known_variables,
            known_parameters=known_parameters,
            known_concepts=known_concepts,
            now=now,
        )
        for formula in analysis.formulas
    ]
