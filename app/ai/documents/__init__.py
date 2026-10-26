"""Document text extraction for the AI pipeline.

Supported: ``.txt``, ``.md``, ``.html`` and ``.pdf`` (via pypdf). Every result is
marked as untrusted content: the text is data for the model, never instructions
for the system.
"""

from app.ai.documents.extraction import ExtractedDocument, extract_document, extract_text

__all__ = ["ExtractedDocument", "extract_document", "extract_text"]
