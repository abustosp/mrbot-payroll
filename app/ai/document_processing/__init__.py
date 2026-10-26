"""Plan-compatible alias for document processing.

The implementation lives in :mod:`app.ai.documents`; this package keeps the
layout named in ``plan.md`` section 5 available to integrators.
"""

from app.ai.document_processing.extraction import ExtractedDocument, extract_document, extract_text

__all__ = ["ExtractedDocument", "extract_document", "extract_text"]
