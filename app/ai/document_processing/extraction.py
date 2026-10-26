"""Re-export the extraction implementation under the plan's package name."""

from app.ai.documents.extraction import (
    SUPPORTED_EXTENSIONS,
    UNTRUSTED_CONTENT_NOTICE,
    ExtractedDocument,
    extract_document,
    extract_text,
)

__all__ = [
    "SUPPORTED_EXTENSIONS",
    "UNTRUSTED_CONTENT_NOTICE",
    "ExtractedDocument",
    "extract_document",
    "extract_text",
]
