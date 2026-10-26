"""Content hashing helpers used for source traceability.

Every source reference must carry the hash of the exact text that was analyzed.
The hash is computed by this package, never trusted from the model.
"""

from __future__ import annotations

import hashlib

CONTENT_HASH_PREFIX = "sha256:"


def compute_content_hash(text: str) -> str:
    """Return ``sha256:<hex>`` for the UTF-8 encoding of ``text``."""

    if not isinstance(text, str):
        raise TypeError("content hash requires a string")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return f"{CONTENT_HASH_PREFIX}{digest}"
