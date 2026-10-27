from __future__ import annotations

import re
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.auth.security import hash_password
from app.config import Settings, get_settings
from app.database import Base
from app.database.models import AiProposal, Company, Organization, User
from app.database.session import get_db
from app.web.auth import CSRF_COOKIE
from app.web.demo_data import DemoDataStore
from app.web.routes import router
from app.web.sql_data_source import SqlAlchemyDataSource


def _test_settings() -> Settings:
    return Settings(
        web_auth_enabled=True,
        admin_email="admin@example.com",
        admin_password="admin",
        secret_key="web-auth-test-secret",
    )


@pytest.fixture()
def app() -> FastAPI:
    application = FastAPI(title="Payroll web auth test")
    application.include_router(router)
    application.state.payroll_data_source = DemoDataStore()
    application.dependency_overrides[get_settings] = _test_settings
    return application


@pytest.fixture()
def client(app: FastAPI) -> Generator[TestClient, None, None]:
    with TestClient(app) as test_client:
        yield test_client


def _csrf_from(html: str) -> str:
    match = re.search(r'name="csrf_token" value="([^"]+)"', html)
    assert match is not None, "No se encontró el token CSRF en el formulario"
    return match.group(1)


def _csrf_cookie(client: TestClient) -> str:
    token = client.cookies.get(CSRF_COOKIE)
    assert token
    return token


def _login(
    client: TestClient,
    *,
    email: str = "admin@example.com",
    password: str = "admin",
    next_url: str = "/",
):
    page = client.get("/login", params={"next": next_url})
    assert page.status_code == 200
    return client.post(
        "/login",
        data={
            "email": email,
            "password": password,
            "next": next_url,
            "csrf_token": _csrf_from(page.text),
        },
        follow_redirects=False,
    )


def test_login_is_public_and_business_routes_redirect(client: TestClient) -> None:
    login = client.get("/login")
    assert login.status_code == 200
    assert "Ingresar" in login.text
    assert 'name="csrf_token"' in login.text

    assert client.get("/salud").status_code == 200
    assert client.get("/static/app.css").status_code == 200

    redirect = client.get("/", follow_redirects=False)
    assert redirect.status_code == 303
    assert "/login?next=" in redirect.headers["location"]

    htmx = client.get(
        "/empresas",
        headers={"HX-Request": "true"},
        follow_redirects=False,
    )
    assert htmx.status_code == 401
    assert "/login?next=" in htmx.headers["HX-Redirect"]


def test_valid_login_and_logout(client: TestClient) -> None:
    response = _login(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert client.cookies.get("payroll_session")

    dashboard = client.get("/")
    assert dashboard.status_code == 200
    assert "admin@example.com" in dashboard.text
    assert "Salir" in dashboard.text
    assert "Modo demo" in dashboard.text

    already_logged_in = client.get("/login", follow_redirects=False)
    assert already_logged_in.status_code == 303

    token = _csrf_cookie(client)
    logout = client.post(
        "/logout",
        data={"csrf_token": token},
        follow_redirects=False,
    )
    assert logout.status_code == 303
    assert logout.headers["location"] == "/login"
    assert client.cookies.get("payroll_session") is None

    protected = client.get("/", follow_redirects=False)
    assert protected.status_code == 303
    assert "/login?next=" in protected.headers["location"]


def test_invalid_login_is_rejected(client: TestClient) -> None:
    page = client.get("/login")
    response = client.post(
        "/login",
        data={
            "email": "admin@example.com",
            "password": "incorrecta",
            "csrf_token": _csrf_from(page.text),
        },
        follow_redirects=False,
    )
    assert response.status_code == 401
    assert "Credenciales inválidas" in response.text
    assert client.cookies.get("payroll_session") is None


def test_login_requires_csrf_token(client: TestClient) -> None:
    client.get("/login")
    response = client.post(
        "/login",
        data={"email": "admin@example.com", "password": "admin"},
        follow_redirects=False,
    )
    assert response.status_code == 403
    assert client.cookies.get("payroll_session") is None


def test_login_honors_local_next_and_rejects_external_redirects(client: TestClient) -> None:
    response = _login(client, next_url="/empresas")
    assert response.status_code == 303
    assert response.headers["location"] == "/empresas"

    client.post(
        "/logout",
        data={"csrf_token": _csrf_cookie(client)},
        follow_redirects=False,
    )
    external = _login(client, next_url="https://evil.example/robo")
    assert external.status_code == 303
    assert external.headers["location"] == "/"

    client.post(
        "/logout",
        data={"csrf_token": _csrf_cookie(client)},
        follow_redirects=False,
    )
    protocol_relative = _login(client, next_url="//evil.example/robo")
    assert protocol_relative.status_code == 303
    assert protocol_relative.headers["location"] == "/"


def test_proposal_status_requires_csrf(client: TestClient) -> None:
    _login(client)

    missing = client.post(
        "/propuestas-ia/prop-001/estado",
        data={"status": "approved"},
        follow_redirects=False,
    )
    assert missing.status_code == 403

    tampered = client.post(
        "/propuestas-ia/prop-001/estado",
        data={"status": "approved", "csrf_token": "token-falso"},
        follow_redirects=False,
    )
    assert tampered.status_code == 403

    valid = client.post(
        "/propuestas-ia/prop-001/estado",
        data={"status": "approved", "csrf_token": _csrf_cookie(client)},
        follow_redirects=False,
    )
    assert valid.status_code == 303
    assert "updated=1" in valid.headers["location"]


def test_logout_requires_csrf(client: TestClient) -> None:
    _login(client)

    missing = client.post("/logout", data={}, follow_redirects=False)
    assert missing.status_code == 403
    assert client.get("/").status_code == 200

    valid = client.post(
        "/logout",
        data={"csrf_token": _csrf_cookie(client)},
        follow_redirects=False,
    )
    assert valid.status_code == 303


def test_demo_logout_revokes_copied_session_cookie(
    app: FastAPI,
    client: TestClient,
) -> None:
    """V2-01: la cookie demo copiada antes del logout deja de aceptarse."""

    assert _login(client).status_code == 303
    copied = client.cookies.get("payroll_session")
    assert copied

    logout = client.post(
        "/logout",
        data={"csrf_token": _csrf_cookie(client)},
        follow_redirects=False,
    )
    assert logout.status_code == 303

    with TestClient(app) as attacker:
        attacker.cookies.set("payroll_session", copied)
        replay = attacker.get("/", follow_redirects=False)
    assert replay.status_code == 303
    assert "/login?next=" in replay.headers["location"]


def test_sql_logout_bumps_session_version_and_rejects_old_cookie(tmp_path: Path) -> None:
    """V2-01: el logout web en SQL rota session_version como el de la API."""

    engine = create_engine(f"sqlite:///{tmp_path / 'web-logout.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        organization = Organization(name="Test", slug="default")
        session.add(organization)
        session.flush()
        session.add(
            User(
                organization_id=organization.id,
                email="logout@example.test",
                password_hash=hash_password("secret"),
                role="admin",
            )
        )

    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_settings] = _test_settings
    try:
        with TestClient(application) as client:
            assert _login(client, email="logout@example.test", password="secret").status_code == 303
            copied = client.cookies.get("payroll_session")
            assert copied
            with factory() as session:
                before = session.scalar(
                    select(User).where(User.email == "logout@example.test")
                ).session_version
            logout = client.post(
                "/logout",
                data={"csrf_token": _csrf_cookie(client)},
                follow_redirects=False,
            )
            assert logout.status_code == 303
            with factory() as session:
                after = session.scalar(
                    select(User).where(User.email == "logout@example.test")
                ).session_version
            assert after == before + 1

        with TestClient(application) as attacker:
            attacker.cookies.set("payroll_session", copied)
            replay = attacker.get("/", follow_redirects=False)
        assert replay.status_code == 303
        assert "/login?next=" in replay.headers["location"]
    finally:
        application.dependency_overrides.clear()
        engine.dispose()


def _sql_salud_app(tmp_path: Path, name: str, *, create_tables: bool):
    engine = create_engine(f"sqlite:///{tmp_path / name}")
    if create_tables:
        Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    if create_tables:
        with factory.begin() as session:
            organization = Organization(name="Test", slug="default")
            session.add(organization)

    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_settings] = _test_settings
    return application, engine


def test_salud_sql_probes_real_connection(tmp_path: Path) -> None:
    """PW-1: /salud en modo SQL informa la conexión real (tabla users)."""

    application, engine = _sql_salud_app(tmp_path, "web-salud-ok.sqlite", create_tables=True)
    try:
        with TestClient(application) as client:
            response = client.get("/salud")
        assert response.status_code == 200
        assert "conectada" in response.text
        assert "users" in response.text
    finally:
        application.dependency_overrides.clear()
        engine.dispose()


def test_salud_sql_reports_degraded_when_db_unavailable(tmp_path: Path) -> None:
    """PW-1: /salud en modo SQL degrada si la base no responde."""

    application, engine = _sql_salud_app(tmp_path, "web-salud-broken.sqlite", create_tables=False)
    try:
        with TestClient(application) as client:
            response = client.get("/salud")
        assert response.status_code == 200
        assert "no disponible" in response.text
    finally:
        application.dependency_overrides.clear()
        engine.dispose()


def test_auth_can_be_disabled_with_explicit_override(tmp_path: Path) -> None:
    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = DemoDataStore()
    application.dependency_overrides[get_settings] = lambda: Settings(web_auth_enabled=False)
    with TestClient(application) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Modo demo" in response.text


def test_viewer_can_read_but_cannot_change_proposal_status(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-auth.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        organization = Organization(name="Test", slug="default")
        session.add(organization)
        session.flush()
        session.add(
            User(
                organization_id=organization.id,
                email="viewer@example.test",
                password_hash=hash_password("viewer-pass"),
                role="viewer",
            )
        )

    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_settings] = _test_settings

    try:
        with TestClient(application) as client:
            response = _login(
                client,
                email="viewer@example.test",
                password="viewer-pass",
            )
            assert response.status_code == 303

            dashboard = client.get("/")
            assert dashboard.status_code == 200
            assert "viewer@example.test" in dashboard.text
            assert "Solo lectura" in dashboard.text
            assert "Base de datos SQL" in dashboard.text
            assert "Modo demo" not in dashboard.text

            proposals = client.get("/propuestas-ia")
            assert proposals.status_code == 200

            forbidden = client.post(
                "/propuestas-ia/prop-001/estado",
                data={"status": "approved", "csrf_token": _csrf_cookie(client)},
                follow_redirects=False,
            )
            assert forbidden.status_code == 403

            with factory.begin() as session:
                viewer = session.scalar(select(User).where(User.email == "viewer@example.test"))
                assert viewer is not None
                viewer.session_version += 1

            stale_session = client.get("/", follow_redirects=False)
            assert stale_session.status_code == 303
            assert "/login?next=" in stale_session.headers["location"]
    finally:
        engine.dispose()


def test_sql_web_pages_are_scoped_to_the_authenticated_organization(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'web-org-scope.sqlite'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory.begin() as session:
        org_a = Organization(name="Organización A", slug="org-a")
        org_b = Organization(name="Organización B", slug="org-b")
        session.add_all([org_a, org_b])
        session.flush()
        session.add_all(
            [
                User(
                    organization_id=org_a.id,
                    email="admin-a@example.test",
                    password_hash=hash_password("secret-a"),
                    role="admin",
                ),
                User(
                    organization_id=org_b.id,
                    email="admin-b@example.test",
                    password_hash=hash_password("secret-b"),
                    role="admin",
                ),
                Company(
                    organization_id=org_a.id,
                    cuit="30733333332",
                    legal_name="Empresa Visible A",
                    active=True,
                ),
                Company(
                    organization_id=org_b.id,
                    cuit="30744444443",
                    legal_name="Empresa Oculta B",
                    active=True,
                ),
                AiProposal(
                    organization_id=org_a.id,
                    document_id="doc-a",
                    title="Propuesta Visible A",
                    raw_json={"summary": "Resumen A", "agreement_number": "130/75"},
                    status="draft",
                ),
                AiProposal(
                    organization_id=org_b.id,
                    document_id="doc-b",
                    title="Propuesta Oculta B",
                    raw_json={"summary": "Resumen B", "agreement_number": "260/75"},
                    status="draft",
                ),
            ]
        )

    application = FastAPI()
    application.include_router(router)
    application.state.payroll_data_source = SqlAlchemyDataSource(factory)

    def override_db() -> Generator[Session, None, None]:
        with factory() as session:
            yield session

    application.dependency_overrides[get_db] = override_db
    application.dependency_overrides[get_settings] = _test_settings
    try:
        with TestClient(application) as client_a:
            response = _login(
                client_a,
                email="admin-a@example.test",
                password="secret-a",
            )
            assert response.status_code == 303
            companies = client_a.get("/empresas")
            assert companies.status_code == 200
            assert "Empresa Visible A" in companies.text
            assert "Empresa Oculta B" not in companies.text
            employees = client_a.get("/empleados")
            assert employees.status_code == 200
            assert "Empresa Oculta B" not in employees.text
            proposals = client_a.get("/propuestas-ia")
            assert proposals.status_code == 200
            assert "Propuesta Visible A" in proposals.text
            assert "Propuesta Oculta B" not in proposals.text

        with TestClient(application) as client_b:
            response = _login(
                client_b,
                email="admin-b@example.test",
                password="secret-b",
            )
            assert response.status_code == 303
            companies = client_b.get("/empresas")
            assert companies.status_code == 200
            assert "Empresa Oculta B" in companies.text
            assert "Empresa Visible A" not in companies.text
            proposals = client_b.get("/propuestas-ia")
            assert proposals.status_code == 200
            assert "Propuesta Oculta B" in proposals.text
            assert "Propuesta Visible A" not in proposals.text
    finally:
        application.dependency_overrides.clear()
        engine.dispose()
