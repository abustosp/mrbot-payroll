import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# La suite nunca toca la red: un .env con credenciales reales no debe cambiar
# el provider seleccionado. Se fijan vacias en el proceso (precedencia sobre
# el archivo .env); cada test que necesite un valor lo define explicitamente.
_AI_ENV_VARS = (
    "PAYROLL_AI_PROVIDER",
    "PAYROLL_META_API_KEY",
    "PAYROLL_META_BASE_URL",
    "PAYROLL_META_MODEL",
    "PAYROLL_AI_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_BASE_URL",
    "MODEL_API_KEY",
)


@pytest.fixture(autouse=True)
def _isolate_ai_provider_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in _AI_ENV_VARS:
        monkeypatch.setenv(name, "")


@pytest.fixture
def project_root() -> Path:
    return ROOT

