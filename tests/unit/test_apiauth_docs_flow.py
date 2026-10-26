"""B-41: el flujo IA de 3 llamadas es visible en /docs (openapi + ejemplos)."""

from fastapi.testclient import TestClient

from app.main import app


def _description(path: str) -> str:
    spec = TestClient(app).get("/openapi.json").json()
    return spec["paths"][path]["post"].get("description", "")


def test_ai_flow_steps_are_documented_in_openapi() -> None:
    assert "paso 1 de 3" in _description("/api/v1/ai/analyze-agreement").lower()
    assert "paso 2 de 3" in _description("/api/v1/ai/proposals").lower()
    assert "paso 3 de 3" in _description("/api/v1/ai/proposals/{proposal_id}/approve").lower()


def test_ai_requests_carry_visible_examples() -> None:
    spec = TestClient(app).get("/openapi.json").json()
    analyze = spec["components"]["schemas"]["AnalyzeAgreementRequest"]
    assert analyze["example"]["document_id"] == "CCT-130-75"
    assert "text" in analyze["example"]
    persist = spec["components"]["schemas"]["PersistProposalRequest"]
    assert "analysis" in persist["example"]
