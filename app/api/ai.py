# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
"""API endpoints for the supervised AI pipeline.

These routes only expose :mod:`app.ai`: they never execute formulas, approve
rules on their own or persist anything in the payroll engine. An approval is a
review record returned to the caller; publication remains a separate, audited
operation.
"""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field

from app.ai import (
    AgreementAnalysis,
    AIError,
    AnalysisError,
    ApprovalError,
    DocumentMetadata,
    DocumentTooLargeError,
    LLMProvider,
    MockProvider,
    ProposedFormula,
    ProviderError,
    ValidationReport,
    analyze_agreement,
    approve_proposal,
    validate_formula_proposal,
    validate_proposal,
)
from app.auth.dependencies import require_role, require_user
from app.database.models import User

router = APIRouter(prefix="/ai", tags=["ai"])

# The API keeps a smaller ceiling than the pipeline default so a malformed or
# abusive request is rejected before prompts, hashes and validation run.
MAX_AGREEMENT_TEXT_CHARS = 100_000
_MOCK_EFFECTIVE_FROM = "2026-10-01"


class AnalyzeAgreementRequest(BaseModel):
    """Input for agreement analysis.

    ``text`` is required and is treated as untrusted data by the AI pipeline.
    ``version`` defaults to ``"1"`` because the pipeline needs an explicit
    document version to anchor every source reference.
    """

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: str
    document_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=500)
    version: str = Field(default="1", min_length=1, max_length=100)

    def to_metadata(self) -> DocumentMetadata:
        return DocumentMetadata(
            document_id=self.document_id,
            version=self.version,
            title=self.title,
        )


def _mock_analysis_json(metadata: DocumentMetadata) -> str:
    """Deterministic canned analysis used by the default offline provider.

    The sample is deliberately labelled as a mock in the summary and notes so a
    reviewer cannot mistake it for a real interpretation of the document.
    """

    concept_source = {
        "document_id": metadata.document_id,
        "version": metadata.version,
        "page": 1,
        "article": "Articulo 1",
    }
    parameter_source = {
        "document_id": metadata.document_id,
        "version": metadata.version,
        "page": 1,
        "article": "Articulo 15",
    }
    formula_source = {
        "document_id": metadata.document_id,
        "version": metadata.version,
        "page": 1,
        "article": "Articulo 15",
    }
    payload = {
        "summary": (
            "Analisis mock deterministico para desarrollo y pruebas. No interpreta "
            "efectivamente el texto recibido ni publica reglas de liquidacion."
        ),
        "agreement_number": "MOCK-001",
        "agreement_title": metadata.title,
        "jurisdiction": "Argentina",
        "effective_from": _MOCK_EFFECTIVE_FROM,
        "concepts": [
            {
                "code": "SUELDO_BASICO",
                "name": "Sueldo basico",
                "description": "Concepto de ejemplo generado por el proveedor mock.",
                "nature": "REMUNERATIVE",
                "source": concept_source,
                "effective_from": _MOCK_EFFECTIVE_FROM,
            }
        ],
        "parameters": [
            {
                "code": "PORCENTAJE_ANTIGUEDAD",
                "name": "Porcentaje por anio de antiguedad",
                "description": "Parametro de ejemplo generado por el proveedor mock.",
                "value": "0.01",
                "unit": "percentage",
                "source": parameter_source,
                "effective_from": _MOCK_EFFECTIVE_FROM,
            }
        ],
        "formulas": [
            {
                "code": "ANTIGUEDAD",
                "description": "Adicional por antiguedad (ejemplo mock)",
                "formula": {
                    "operator": "multiply",
                    "arguments": [
                        {"variable": "sueldo_basico"},
                        {"variable": "anios_antiguedad"},
                        {"parameter": "PORCENTAJE_ANTIGUEDAD"},
                    ],
                },
                "rounding": {"decimals": 2, "mode": "HALF_UP"},
                "variables": ["sueldo_basico", "anios_antiguedad"],
                "depends_on": [],
                "nature": "REMUNERATIVE",
                "source": formula_source,
                "effective_from": _MOCK_EFFECTIVE_FROM,
                "tests": [
                    {
                        "name": "caso base",
                        "description": "5 anios de antiguedad sobre un basico de 1000000",
                        "inputs": {
                            "sueldo_basico": "1000000",
                            "anios_antiguedad": "5",
                        },
                        "expected": "50000",
                        "period": _MOCK_EFFECTIVE_FROM,
                        "tolerance": "0",
                    }
                ],
            }
        ],
        "ambiguities": [
            "Resultado de ejemplo: no se interpretaron las clausulas del documento real."
        ],
        "notes": ["Generado por MockProvider. Requiere revision humana antes de cualquier uso."],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def get_ai_provider(payload: AnalyzeAgreementRequest) -> LLMProvider:
    """Provide the default offline provider.

    Deployments and tests can override this FastAPI dependency to inject a real
    ``LLMProvider`` without changing the route logic.
    """

    return MockProvider(_mock_analysis_json(payload.to_metadata()))


def _with_validation_reports(analysis: AgreementAnalysis) -> AgreementAnalysis:
    """Attach deterministic reports while keeping every proposal in ``draft``.

    This is not an approval: the formula status is untouched and nothing is
    persisted. Each report is produced with the full analysis context so
    parameter, concept and dependency references can be checked.
    """

    formulas = [
        formula.model_copy(
            update={
                "validation": validate_formula_proposal(formula, analysis=analysis),
            }
        )
        for formula in analysis.formulas
    ]
    return analysis.model_copy(update={"formulas": formulas})


@router.post("/analyze-agreement", response_model=AgreementAnalysis)
def analyze_agreement_endpoint(
    payload: AnalyzeAgreementRequest,
    provider: LLMProvider = Depends(get_ai_provider),
    _user: User = Depends(require_user),
) -> AgreementAnalysis:
    """Analyze agreement text and return draft proposals. Never publishes."""

    if len(payload.text) > MAX_AGREEMENT_TEXT_CHARS:
        raise HTTPException(
            status_code=413,
            detail=(
                f"El texto del convenio supera el limite de {MAX_AGREEMENT_TEXT_CHARS} caracteres."
            ),
        )
    if not payload.text.strip():
        raise HTTPException(
            status_code=422,
            detail="El texto del convenio no puede estar vacio.",
        )

    try:
        analysis = analyze_agreement(
            payload.text,
            provider,
            payload.to_metadata(),
            max_chars=MAX_AGREEMENT_TEXT_CHARS,
        )
    except DocumentTooLargeError as exc:
        raise HTTPException(
            status_code=413,
            detail=str(exc),
        ) from exc
    except AnalysisError as exc:
        raise HTTPException(
            status_code=422,
            detail=str(exc),
        ) from exc
    except ProviderError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"El proveedor de IA fallo: {exc}",
        ) from exc
    except AIError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return _with_validation_reports(analysis)


@router.post("/proposals/validate", response_model=ValidationReport)
def validate_ai_proposal(
    proposal: ProposedFormula,
    _user: User = Depends(require_user),
) -> ValidationReport:
    """Validate a proposal structurally and return its report.

    An invalid proposal is still a successful validation request: the response
    carries ``is_valid == false`` and the list of errors. Nothing is persisted.
    """

    return validate_formula_proposal(proposal)


@router.post("/proposals/approve", response_model=ProposedFormula)
def approve_ai_proposal(
    proposal: ProposedFormula,
    user: User = Depends(require_role("admin", "editor")),
) -> ProposedFormula:
    """Record a human approval using the authenticated user's identity.

    The client-supplied ``approved_by`` is not trusted: it is overwritten with
    the authenticated user's email (or ``user:<id>`` when no email is stored)
    before validation and approval. The endpoint re-runs the deterministic
    validation, rejects invalid proposals, and never writes to the database or
    publishes the rule.
    """

    authenticated_identity = (user.email or "").strip() or f"user:{user.id}"
    authenticated_proposal = proposal.model_copy(update={"approved_by": authenticated_identity})

    validated = validate_proposal(authenticated_proposal)
    report = validated.validation
    if report is None or not report.is_valid:
        errors = (
            [] if report is None else [issue.model_dump(mode="json") for issue in report.errors]
        )
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La propuesta no supera la validacion deterministica.",
                "errors": errors,
            },
        )

    try:
        return approve_proposal(validated, authenticated_identity)
    except ApprovalError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
