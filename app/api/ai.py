# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
"""API endpoints for the supervised AI pipeline.

These routes only expose :mod:`app.ai`: they never execute formulas, approve
rules on their own or persist anything in the payroll engine. An approval is a
review record returned to the caller; publication remains a separate, audited
operation.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai import (
    AgreementAnalysis,
    AIError,
    AnalysisError,
    ApprovalError,
    DocumentMetadata,
    DocumentTooLargeError,
    LLMProvider,
    MetaMuseProvider,
    MockProvider,
    OpenAICompatibleProvider,
    ProposedFormula,
    ProposedParameter,
    ProviderConfigurationError,
    ProviderError,
    ValidationReport,
    analyze_agreement,
    approve_proposal,
    parse_scales,
    validate_formula_proposal,
    validate_proposal,
)
from app.api.common import commit_or_conflict, get_scoped
from app.api.schemas import AiProposalPublishRead, AiProposalRead
from app.auth.dependencies import require_role, require_user
from app.config import Settings, get_settings
from app.database.models import (
    AiProposal,
    AuditLog,
    FormulaDefinition,
    FormulaVersion,
    User,
)
from app.database.session import get_db

router = APIRouter(prefix="/ai", tags=["ai"])

# The API keeps a smaller ceiling than the pipeline default so a malformed or
# abusive request is rejected before prompts, hashes and validation run.
MAX_AGREEMENT_TEXT_CHARS = 100_000
MAX_SCALE_ROWS = 1000
_MOCK_EFFECTIVE_FROM = "2026-10-01"


class PersistProposalRequest(BaseModel):
    """Optional wrapper for clients that post ``{"analysis": {...}}``."""

    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "example": {
                "analysis": {
                    "document": {
                        "document_id": "CCT-130-75",
                        "version": "1",
                        "content_hash": None,
                    },
                    "summary": "Pegue aquí el JSON íntegro devuelto por analyze-agreement.",
                    "analyzed_at": "2026-10-26T12:00:00+00:00",
                }
            }
        },
    )

    analysis: AgreementAnalysis


class AnalyzeAgreementRequest(BaseModel):
    """Input for agreement analysis.

    ``text`` is required and is treated as untrusted data by the AI pipeline.
    ``version`` defaults to ``"1"`` because the pipeline needs an explicit
    document version to anchor every source reference.
    """

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        json_schema_extra={
            "example": {
                "text": "Artículo 15: adicional por antigüedad del 1% por año de servicio.",
                "document_id": "CCT-130-75",
                "title": "Empleados de Comercio",
                "version": "1",
            }
        },
    )

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


class ParseScalesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    document_id: str = Field(min_length=1, max_length=200)
    version: str = Field(default="1", min_length=1, max_length=100)
    title: str | None = Field(default=None, max_length=500)
    scales: list[dict] = Field(json_schema_extra={"maxItems": MAX_SCALE_ROWS})


class ParseScalesResult(BaseModel):
    parameters: list[ProposedParameter]
    formulas: list[ProposedFormula]
    skipped: list[str]


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


def get_ai_provider(
    payload: AnalyzeAgreementRequest,
    settings: Settings = Depends(get_settings),
) -> LLMProvider:
    """Select an explicit provider or fall back to the environment.

    ``development``/``test`` keep the deterministic mock so the suite and local
    runs stay offline. Any other environment requires a real provider: with a
    key it returns ``OpenAICompatibleProvider``, without one it fails with
    503 explícito. ``PAYROLL_AI_PROVIDER`` can select ``meta`` or ``mock``.
    Settings (proceso o archivo .env) tiene prioridad; el entorno del proceso
    se consulta como respaldo para compatibilidad.
    Deployments and tests can still override this FastAPI
    dependency to inject any ``LLMProvider`` (D-4).
    """

    selected = (
        getattr(settings, "ai_provider", "")
        or os.environ.get("PAYROLL_AI_PROVIDER", "")
        or ""
    ).strip().lower()
    if selected == "mock" or (
        selected != "meta"
        and (settings.environment or "").strip().lower() in {"development", "dev", "test", "testing"}
    ):
        return MockProvider(_mock_analysis_json(payload.to_metadata()))
    try:
        if selected == "meta":
            return MetaMuseProvider(
                api_key=getattr(settings, "meta_api_key", "") or None,
                base_url=getattr(settings, "meta_base_url", "") or None,
                model=getattr(settings, "meta_model", "") or None,
            )
        return OpenAICompatibleProvider()
    except ProviderConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Proveedor IA no configurado: defina PAYROLL_META_API_KEY "
                "(o MODEL_API_KEY) o PAYROLL_AI_API_KEY (o OPENAI_API_KEY) "
                f"o despliegue en development/test para usar el mock. Detalle: {exc}"
            ),
        ) from exc


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


def _reports_for_analysis(analysis: AgreementAnalysis) -> list[ValidationReport]:
    return [
        validate_formula_proposal(formula, analysis=analysis)
        for formula in analysis.formulas
    ]


def _validation_summary(reports: list[ValidationReport]) -> dict[str, Any]:
    return {
        "is_valid": all(report.is_valid for report in reports),
        "reports": [report.model_dump(mode="json") for report in reports],
        "validated_at": datetime.now(UTC).isoformat(),
    }


def _stored_validation_is_valid(value: Any) -> bool:
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            return False
    if isinstance(value, dict):
        return value.get("is_valid") is True
    if isinstance(value, list):
        return bool(value) and all(
            isinstance(item, dict) and item.get("is_valid") is True for item in value
        )
    return False


def _analysis_from_proposal(proposal: AiProposal) -> AgreementAnalysis:
    raw = proposal.raw_json
    try:
        if isinstance(raw, str):
            raw = json.loads(raw)
        return AgreementAnalysis.model_validate(raw)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"La propuesta persistida no contiene un análisis válido: {exc}",
        ) from exc


def _ensure_valid_reports(reports: list[ValidationReport]) -> None:
    invalid = [report for report in reports if not report.is_valid]
    if invalid:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "La propuesta no supera la validación determinística.",
                "errors": [
                    issue.model_dump(mode="json")
                    for report in invalid
                    for issue in report.errors
                ],
            },
        )


@router.post(
    "/proposals",
    response_model=AiProposalRead,
    status_code=status.HTTP_201_CREATED,
)
def create_ai_proposal(
    payload: AgreementAnalysis | PersistProposalRequest,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Persist a validated analysis as a draft proposal (paso 2 de 3).

    Flujo supervisado: 1) ``POST /ai/analyze-agreement`` con
    ``{"text", "document_id"}``; 2) este endpoint con el JSON íntegro del
    análisis (o ``{"analysis": {...}}``, ver ejemplo); 3)
    ``POST /ai/proposals/{id}/approve`` y luego ``publish`` (solo admin).
    Persistence is not an approval: the stored status is always ``draft`` and
    no formula definition is created.
    """

    if isinstance(payload, PersistProposalRequest):
        payload = payload.analysis
    reports = _reports_for_analysis(payload)
    _ensure_valid_reports(reports)
    row = AiProposal(
        organization_id=user.organization_id,
        document_id=payload.document.document_id,
        document_hash=payload.document.content_hash,
        title=payload.document.title or payload.agreement_title,
        raw_json=payload.model_dump(mode="json"),
        validation_json=_validation_summary(reports),
        status="draft",
    )
    db.add(row)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.post("/proposals/{proposal_id}/approve", response_model=AiProposalRead)
def approve_persisted_ai_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin", "editor")),
):
    """Approve a persisted, valid draft/validated proposal (paso 3 de 3).

    The approval is recorded with the authenticated user's identity. It does
    not publish anything or create a formula: publishing is a separate
    ``POST /ai/proposals/{id}/publish`` (solo admin) that creates DRAFT
    formula versions, never production rules.
    """

    row = get_scoped(db, AiProposal, proposal_id, user.organization_id)
    if row.status not in {"draft", "validated"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se aprueban propuestas en estado draft o validated",
        )
    if not _stored_validation_is_valid(row.validation_json):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La propuesta no tiene una validación determinística satisfactoria",
        )
    analysis = _analysis_from_proposal(row)
    _ensure_valid_reports(_reports_for_analysis(analysis))

    row.status = "approved"
    row.approved_by = user.id
    row.approved_at = datetime.now(UTC)
    commit_or_conflict(db)
    db.refresh(row)
    return row


@router.post(
    "/proposals/{proposal_id}/publish",
    response_model=AiProposalPublishRead,
)
def publish_ai_proposal(
    proposal_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(require_role("admin")),
):
    """Publish an approved proposal as *draft* formula versions.

    Only administrators may publish. Every created version is ``DRAFT``: the
    endpoint never copies an approval into production rules. An existing
    formula with the same code is a conflict, never silently reused.
    """

    row = get_scoped(db, AiProposal, proposal_id, user.organization_id)
    if row.status != "approved":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La propuesta debe estar aprobada antes de publicarse",
        )
    analysis = _analysis_from_proposal(row)
    _ensure_valid_reports(_reports_for_analysis(analysis))
    if not analysis.formulas:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="La propuesta no contiene fórmulas para publicar",
        )

    for formula in analysis.formulas:
        if len(formula.code) > 80:
            raise HTTPException(
                status_code=422,
                detail=f"El código {formula.code!r} supera el máximo de 80 caracteres",
            )
        existing = db.scalar(
            select(FormulaDefinition).where(
                FormulaDefinition.organization_id == user.organization_id,
                FormulaDefinition.code == formula.code,
            )
        )
        if existing is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=(
                    f"Ya existe una fórmula con el código {formula.code!r}; "
                    "no se reutiliza silenciosamente. Cree una nueva versión explícita."
                ),
            )

    published: list[tuple[FormulaDefinition, FormulaVersion]] = []
    for formula in analysis.formulas:
        definition = FormulaDefinition(
            organization_id=user.organization_id,
            code=formula.code,
            description=formula.description[:240],
            current_version=1,
        )
        db.add(definition)
        db.flush()
        version = FormulaVersion(
            formula_id=definition.id,
            version=1,
            expression=formula.formula,
            status="DRAFT",
            valid_from=formula.effective_from,
            valid_to=formula.effective_to,
        )
        db.add(version)
        db.flush()
        published.append((definition, version))

    first_definition, first_version = published[0]
    row.status = "published"
    row.published_formula_id = first_definition.id
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            user_id=user.id,
            action="ai_proposal.published",
            entity_type="AiProposal",
            entity_id=str(row.id),
            before={"status": "approved"},
            after={
                "status": "published",
                "published_formula_id": first_definition.id,
                "formulas": [
                    {
                        "formula_id": definition.id,
                        "formula_version_id": version.id,
                        "code": definition.code,
                        "version": version.version,
                        "status": version.status,
                    }
                    for definition, version in published
                ],
            },
        )
    )
    commit_or_conflict(db)
    db.refresh(row)
    base = AiProposalRead.model_validate(row)
    return AiProposalPublishRead(
        **base.model_dump(),
        formula_id=first_definition.id,
        formula_version_id=first_version.id,
        formula_status=first_version.status,
    )


@router.post("/parse-scales", response_model=ParseScalesResult)
def parse_scales_endpoint(
    payload: ParseScalesRequest,
    _user: User = Depends(require_user),
) -> ParseScalesResult:
    if len(payload.scales) > MAX_SCALE_ROWS:
        raise HTTPException(status_code=413, detail=f"Maximo de {MAX_SCALE_ROWS} filas de escala.")
    metadata = DocumentMetadata(
        document_id=payload.document_id, version=payload.version, title=payload.title
    )
    parameters, formulas, skipped = parse_scales(payload.scales, metadata)
    known_parameters = [parameter.code for parameter in parameters]
    formulas = [
        formula.model_copy(
            update={"validation": validate_formula_proposal(formula, known_parameters=known_parameters)}
        )
        for formula in formulas
    ]
    return ParseScalesResult(parameters=parameters, formulas=formulas, skipped=skipped)


@router.post("/analyze-agreement", response_model=AgreementAnalysis)
def analyze_agreement_endpoint(
    payload: AnalyzeAgreementRequest,
    provider: LLMProvider = Depends(get_ai_provider),
    _user: User = Depends(require_user),
) -> AgreementAnalysis:
    """Analyze agreement text and return draft proposals (paso 1 de 3).

    Send ``{"text", "document_id"}`` (ver ejemplo). Copy the returned JSON
    unchanged into ``POST /ai/proposals`` (paso 2) and then approve it
    (paso 3). Never publishes.
    """

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
