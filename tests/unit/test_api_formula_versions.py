from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.service import seed_admin
from app.database import Base, models  # noqa: F401
from app.database.models import AuditLog, FormulaVersion, User
from app.database.session import get_db
from app.main import app

PASSWORD = "a-long-test-password"
VALID_FORMULA = {
    "operator": "add",
    "arguments": [{"constant": "10"}, {"constant": "2.5"}],
}


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'formula-versions.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        admin = seed_admin(db, "admin@example.test", PASSWORD)
        db.add(
            User(
                organization_id=admin.organization_id,
                email="viewer@example.test",
                password_hash=admin.password_hash,
                role="viewer",
            )
        )
        db.commit()
    with TestClient(app) as client:
        yield client, local_session
    app.dependency_overrides.clear()
    engine.dispose()


def login(client: TestClient, email: str = "admin@example.test") -> None:
    response = client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
    assert response.status_code == 200, response.text


def create_formula(
    client: TestClient,
    *,
    code: str = "BASICO",
    valid_from: str = "2026-01-01",
    valid_to: str | None = "2026-06-30",
) -> dict:
    response = client.post(
        "/api/v1/formulas",
        json={
            "code": code,
            "description": "Formula versionada",
            "formula": VALID_FORMULA,
            "valid_from": valid_from,
            "valid_to": valid_to,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def create_version(
    client: TestClient,
    formula_id: int,
    *,
    valid_from: str = "2026-07-01",
    valid_to: str | None = "2026-12-31",
    formula: dict | None = None,
):
    return client.post(
        f"/api/v1/formulas/{formula_id}/versions",
        json={
            "formula": VALID_FORMULA if formula is None else formula,
            "valid_from": valid_from,
            "valid_to": valid_to,
        },
    )


def test_create_next_version_keeps_approved_version_untouched(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    login(client)
    formula = create_formula(client)
    formula_id = formula["id"]
    assert client.post(f"/api/v1/formulas/{formula_id}/validate").status_code == 200
    assert client.post(f"/api/v1/formulas/{formula_id}/approve").json()["status"] == "APPROVED"

    response = create_version(client, formula_id)

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["id"] == formula_id
    assert payload["code"] == "BASICO"
    assert payload["version"] == 2
    assert payload["status"] == "DRAFT"
    assert payload["valid_from"] == "2026-07-01"
    assert payload["valid_to"] == "2026-12-31"
    assert payload["formula"] == VALID_FORMULA

    with sessions() as db:
        versions = db.scalars(
            select(FormulaVersion)
            .where(FormulaVersion.formula_id == formula_id)
            .order_by(FormulaVersion.version)
        ).all()
        assert [version.version for version in versions] == [1, 2]
        assert versions[0].status == "APPROVED"
        assert versions[0].approved_by is not None
        assert versions[0].expression == VALID_FORMULA
        assert versions[1].status == "DRAFT"
        assert versions[1].approved_by is None
        audits = db.scalars(
            select(AuditLog).where(AuditLog.entity_type == "FormulaVersion")
        ).all()
        assert len(audits) == 1
        assert audits[0].action == "formula.version_created"
        assert audits[0].entity_id == str(versions[1].id)

    listed = client.get("/api/v1/formulas").json()["items"][0]
    assert listed["version"] == 2
    assert listed["status"] == "DRAFT"


def test_overlapping_validity_is_allowed_and_next_version_wins(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = create_version(
        client,
        formula_id,
        valid_from="2026-06-15",
        valid_to="2026-08-15",
    )

    assert response.status_code == 201, response.text
    assert response.json()["version"] == 2
    assert response.json()["status"] == "DRAFT"
    with sessions() as db:
        versions = db.scalars(
            select(FormulaVersion)
            .where(FormulaVersion.formula_id == formula_id)
            .order_by(FormulaVersion.version)
        ).all()
        assert [version.version for version in versions] == [1, 2]
        assert versions[0].valid_from.isoformat() == "2026-01-01"
        assert versions[0].valid_to.isoformat() == "2026-06-30"
        assert versions[1].valid_from.isoformat() == "2026-06-15"
        assert versions[1].valid_to.isoformat() == "2026-08-15"

    listed = client.get("/api/v1/formulas").json()["items"][0]
    assert listed["version"] == 2
    assert listed["status"] == "DRAFT"


def test_version_with_invalid_dsl_is_rejected(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, sessions = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = create_version(
        client,
        formula_id,
        formula={"operator": "not_a_real_operator", "arguments": []},
    )

    assert response.status_code == 422
    with sessions() as db:
        assert len(db.scalars(select(FormulaVersion)).all()) == 1


def test_version_validity_range_is_enforced(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = create_version(
        client,
        formula_id,
        valid_from="2026-08-01",
        valid_to="2026-07-01",
    )

    assert response.status_code == 422


def test_expression_alias_is_accepted(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = client.post(
        f"/api/v1/formulas/{formula_id}/versions",
        json={
            "expression": VALID_FORMULA,
            "valid_from": "2026-07-01",
            "valid_to": "2026-12-31",
        },
    )

    assert response.status_code == 201, response.text
    assert response.json()["formula"] == VALID_FORMULA


def test_viewer_cannot_create_formula_version(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api
    login(client)
    formula_id = create_formula(client)["id"]
    login(client, "viewer@example.test")

    response = create_version(client, formula_id)

    assert response.status_code == 403


def test_version_with_unknown_variable_is_rejected(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    # B-08: sin contexto la referencia rota llegaba a APPROVED; con contexto
    # la puerta la frena con el nombre de la variable.
    client, _ = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = create_version(
        client, formula_id, formula={"variable": "sueldo_inexistente"}
    )

    assert response.status_code == 422, response.text
    assert "sueldo_inexistente" in response.text


def test_version_with_unknown_concept_is_rejected(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    client, _ = api
    login(client)
    formula_id = create_formula(client)["id"]

    response = create_version(
        client, formula_id, formula={"concept": "FANTASMA"}
    )

    assert response.status_code == 422, response.text
    assert "FANTASMA" in response.text


def test_version_with_known_inputs_and_conditions_is_stored(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    # B-07/B-08: variables base + conditions válidas pasan y se persisten.
    client, sessions = api
    login(client)
    formula_id = create_formula(client)["id"]
    conditions = [{"field": "sueldo_basico", "operator": "greater_than", "value": 0}]

    response = client.post(
        f"/api/v1/formulas/{formula_id}/versions",
        json={
            "formula": {"variable": "sueldo_basico"},
            "conditions": conditions,
            "depends_on": [],
            "rounding": {"decimals": 2, "mode": "HALF_UP"},
            "valid_from": "2026-07-01",
            "valid_to": "2026-12-31",
        },
    )

    assert response.status_code == 201, response.text
    payload = response.json()
    assert payload["conditions"] == conditions
    assert payload["rounding"] == {"decimals": 2, "mode": "HALF_UP"}
    with sessions() as db:
        version = db.scalar(
            select(FormulaVersion).where(
                FormulaVersion.formula_id == formula_id,
                FormulaVersion.version == 2,
            )
        )
        assert version is not None
        assert version.conditions == conditions


def test_cross_formula_cycle_is_rejected(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    # B-08: el ciclo A<->B se detecta contra las vigentes de la organización.
    client, _ = api
    login(client)
    formula_a = create_formula(client, code="CICLO_A", valid_to=None)["id"]
    formula_b = create_formula(client, code="CICLO_B", valid_to=None)["id"]

    first = create_version(client, formula_a, formula={"concept": "CICLO_B"})
    assert first.status_code == 201, first.text
    second = create_version(client, formula_b, formula={"concept": "CICLO_A"})

    assert second.status_code == 422, second.text
    assert "circular" in second.text


def test_formula_scope_rejects_unknown_codes_and_accepts_known(
    api: tuple[TestClient, sessionmaker[Session]],
) -> None:
    # B-26: el scope por convenio valida contra convenios/categorías reales.
    client, local_session = api
    login(client)
    formula_id = create_formula(client, code="CON_SCOPE")["id"]

    unknown = client.patch(
        f"/api/v1/formulas/{formula_id}/scope", json={"agreement_code": "999/99"}
    )
    assert unknown.status_code == 422, unknown.text

    with local_session.begin() as db:
        agreement = models.CollectiveAgreement(code="130/75", year=1975, name="Comercio")
        db.add(agreement)
        db.flush()
        db.add(
            models.AgreementCategory(
                agreement_id=agreement.id, code="ADMIN_A", name="Administrativo A"
            )
        )

    scoped = client.patch(
        f"/api/v1/formulas/{formula_id}/scope",
        json={"agreement_code": "130/75", "category_code": "ADMIN_A"},
    )
    assert scoped.status_code == 200, scoped.text

    bad_category = client.patch(
        f"/api/v1/formulas/{formula_id}/scope",
        json={"agreement_code": "130/75", "category_code": "NOPE"},
    )
    assert bad_category.status_code == 422, bad_category.text

    cleared = client.patch(
        f"/api/v1/formulas/{formula_id}/scope",
        json={"agreement_code": None, "category_code": None},
    )
    assert cleared.status_code == 200, cleared.text
