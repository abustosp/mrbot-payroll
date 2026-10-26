"""Supervised AI pipeline for collective agreement analysis.

The package interprets documents and produces *draft* rule proposals. It never
executes formulas, approves rules on its own or publishes anything to the
payroll engine.
"""

from app.ai.analysis import analyze_agreement
from app.ai.documents.extraction import ExtractedDocument, extract_text
from app.ai.errors import (
    AIError,
    AnalysisError,
    ApprovalError,
    DocumentExtractionError,
    DocumentTooLargeError,
    ProposalError,
    ProviderConfigurationError,
    ProviderError,
    ProviderResponseError,
    UnsupportedDocumentError,
)
from app.ai.hashing import compute_content_hash
from app.ai.proposals import (
    approve_proposal,
    propose_all,
    propose_formula,
    reject_proposal,
)
from app.ai.providers import LLMProvider, MockProvider, OpenAICompatibleProvider
from app.ai.schemas import (
    AgreementAnalysis,
    DocumentMetadata,
    LLMUsage,
    ParameterUnit,
    ProposalStatus,
    ProposedConcept,
    ProposedFormula,
    ProposedParameter,
    SourceReference,
    SuggestedTest,
    ValidationIssue,
    ValidationReport,
)
from app.ai.security import detect_prompt_injection
from app.ai.validation import validate_formula_proposal, validate_proposal

__all__ = [
    "AIError",
    "AgreementAnalysis",
    "AnalysisError",
    "ApprovalError",
    "DocumentExtractionError",
    "DocumentMetadata",
    "DocumentTooLargeError",
    "ExtractedDocument",
    "LLMProvider",
    "LLMUsage",
    "MockProvider",
    "OpenAICompatibleProvider",
    "ParameterUnit",
    "ProposalError",
    "ProposalStatus",
    "ProposedConcept",
    "ProposedFormula",
    "ProposedParameter",
    "ProviderConfigurationError",
    "ProviderError",
    "ProviderResponseError",
    "SourceReference",
    "SuggestedTest",
    "UnsupportedDocumentError",
    "ValidationIssue",
    "ValidationReport",
    "analyze_agreement",
    "approve_proposal",
    "compute_content_hash",
    "detect_prompt_injection",
    "extract_text",
    "propose_all",
    "propose_formula",
    "reject_proposal",
    "validate_formula_proposal",
    "validate_proposal",
]
