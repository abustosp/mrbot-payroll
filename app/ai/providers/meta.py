"""Meta Model API provider (Muse Spark) using the OpenAI-compatible API.

Docs: https://dev.meta.ai/docs/overview -- base URL ``https://api.meta.ai/v1``,
``Authorization: Bearer $MODEL_API_KEY`` and model IDs ``muse-spark-1.3``
(Standard) / ``muse-spark-1.3-contributor`` (Contributor mode).
"""

from __future__ import annotations

import os

from app.ai.providers.openai_compatible import OpenAICompatibleProvider

DEFAULT_META_BASE_URL = "https://api.meta.ai/v1"
DEFAULT_META_MODEL = "muse-spark-1.3-contributor"
DEFAULT_META_API_KEY_ENV = "PAYROLL_META_API_KEY"


class MetaMuseProvider(OpenAICompatibleProvider):
    name = "meta-muse"

    def __init__(self, *, base_url=None, api_key=None, model=None, timeout=None, **kwargs):
        # Las respuestas estructuradas grandes tardan mas que el default de 30s.
        super().__init__(
            base_url=base_url or os.environ.get("PAYROLL_META_BASE_URL") or DEFAULT_META_BASE_URL,
            api_key=(
                api_key
                or os.environ.get(DEFAULT_META_API_KEY_ENV)
                or os.environ.get("MODEL_API_KEY")
                or os.environ.get("PAYROLL_AI_API_KEY")
            ),
            model=model or os.environ.get("PAYROLL_META_MODEL") or DEFAULT_META_MODEL,
            timeout=timeout if timeout is not None else 120.0,
            api_key_env=DEFAULT_META_API_KEY_ENV,
            **kwargs,
        )
