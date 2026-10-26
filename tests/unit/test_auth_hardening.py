from __future__ import annotations

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.api import auth as auth_api
from app.auth.security import (
    login_attempts,
    verify_password,
)
from app.auth.service import seed_admin
from app.database import Base, models  # noqa: F401
from app.database.models import User
from app.database.session import get_db
from app.main import app

ADMIN_EMAIL = "admin@example.test"
LOCKED_EMAIL = "locked@example.test"
PASSWORD = "initial-password-1234"
NEW_PASSWORD = "brand-new-password-5678"


@pytest.fixture
def api(tmp_path) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'auth.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    local_session = sessionmaker(bind=engine, expire_on_commit=False)

    def override_db():
        with local_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    with local_session() as db:
        admin = seed_admin(db, ADMIN_EMAIL, PASSWORD)
        db.add(
            User(
                organization_id=admin.organization_id,
                email=LOCKED_EMAIL,
                password_hash=admin.password_hash,
                role="viewer",
            )
        )
        db.commit()

    login_attempts.clear()
    with TestClient(app) as client:
        yield client, local_session
    login_attempts.clear()
    app.dependency_overrides.clear()
    engine.dispose()


def login(
    client: TestClient,
    *,
    email: str = ADMIN_EMAIL,
    password: str = PASSWORD,
):
    return client.post("/api/v1/auth/login", json={"email": email, "password": password})


def change_password(
    client: TestClient,
    *,
    current: str = PASSWORD,
    new: str = NEW_PASSWORD,
    confirm: str | None = None,
):
    return client.post(
        "/api/v1/auth/change-password",
        json={
            "current_password": current,
            "new_password": new,
            "confirm_password": new if confirm is None else confirm,
        },
    )


def test_change_password_updates_hash_rotates_cookie_and_old_password_fails(api) -> None:
    client, sessions = api
    assert login(client).status_code == 200
    old_cookie = client.cookies.get("payroll_session")
    assert old_cookie

    response = change_password(client)
    assert response.status_code == 204, response.text

    new_cookie = client.cookies.get("payroll_session")
    assert new_cookie
    assert new_cookie != old_cookie
    assert client.get("/api/v1/auth/me").status_code == 200

    client.cookies.set("payroll_session", old_cookie)
    assert client.get("/api/v1/auth/me").status_code == 401
    client.cookies.set("payroll_session", new_cookie)
    assert client.get("/api/v1/auth/me").status_code == 200

    with sessions() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None
        assert verify_password(NEW_PASSWORD, admin.password_hash)
        assert not verify_password(PASSWORD, admin.password_hash)
        assert admin.session_version == 2

    assert login(client, password=PASSWORD).status_code == 401
    assert login(client, password=NEW_PASSWORD).status_code == 200
    assert client.get("/api/v1/auth/me").status_code == 200


def test_change_password_rejects_wrong_current_password(api) -> None:
    client, sessions = api
    assert login(client).status_code == 200

    response = change_password(client, current="not-the-current-password")
    assert response.status_code == 400
    assert "actual" in response.json()["detail"].lower()

    with sessions() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None
        assert verify_password(PASSWORD, admin.password_hash)
        assert not verify_password(NEW_PASSWORD, admin.password_hash)

    assert client.get("/api/v1/auth/me").status_code == 200
    assert login(client).status_code == 200


def test_change_password_validates_length_confirmation_and_reuse(api) -> None:
    client, _ = api
    assert login(client).status_code == 200

    assert change_password(client, new="elevenchars", confirm="elevenchars").status_code == 422
    assert change_password(client, new=NEW_PASSWORD, confirm=NEW_PASSWORD + "-x").status_code == 422
    assert change_password(client, new=PASSWORD, confirm=PASSWORD).status_code == 400

    assert client.get("/api/v1/auth/me").status_code == 200


def test_change_password_requires_authentication(api) -> None:
    client, sessions = api

    response = change_password(client)
    assert response.status_code == 401

    with sessions() as db:
        admin = db.scalar(select(User).where(User.email == ADMIN_EMAIL))
        assert admin is not None
        assert verify_password(PASSWORD, admin.password_hash)


def test_login_still_works_and_uses_dummy_hash_for_unknown_email(api, monkeypatch) -> None:
    client, _ = api
    assert login(client).status_code == 200
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").status_code == 401

    checked_hashes: list[str] = []
    real_verify = auth_api.verify_password

    def spy_verify(password: str, stored: str) -> bool:
        checked_hashes.append(stored)
        return real_verify(password, stored)

    monkeypatch.setattr(auth_api, "verify_password", spy_verify)
    response = login(client, email="missing@example.test", password="whatever-password")
    assert response.status_code == 401
    assert len(checked_hashes) == 1
    assert checked_hashes[0].startswith("pbkdf2_sha256$")

    assert login(client).status_code == 200


def test_login_blocks_temporarily_after_repeated_failures(api) -> None:
    client, _ = api

    for _ in range(5):
        assert login(client, email=LOCKED_EMAIL, password="wrong-password").status_code == 401

    blocked = login(client, email=LOCKED_EMAIL, password=PASSWORD)
    assert blocked.status_code == 429
    assert blocked.json()["detail"] == "Demasiados intentos fallidos. Intente nuevamente más tarde."
    assert int(blocked.headers["Retry-After"]) > 0

    # El bloqueo es por IP + email: otra identidad sigue pudiendo ingresar.
    assert login(client).status_code == 200
