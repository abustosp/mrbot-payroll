"""Autenticación de la interfaz web y protección CSRF.

La UI reutiliza el mismo mecanismo que la API: cookie de sesión firmada con
``itsdangerous``, contraseña PBKDF2 y roles ``admin``, ``editor`` y ``viewer``.
En modo demo no hay tabla de usuarios, por lo que se valida el administrador
configurado (``PAYROLL_ADMIN_EMAIL`` / ``PAYROLL_ADMIN_PASSWORD``). En modo SQL
se consulta la tabla ``users`` con la misma cookie que emite la API.

La protección CSRF usa doble submit: un token firmado vive en una cookie y en
un campo oculto del formulario. El servidor exige que ambos coincidan y que la
firma sea válida antes de aceptar un POST.
"""

# ruff: noqa: B008 -- FastAPI resuelve Depends en tiempo de request.
from __future__ import annotations

import hmac
import re
import secrets
from dataclasses import dataclass
from functools import lru_cache
from typing import Any
from urllib.parse import urlencode, urlsplit

from fastapi import Depends, HTTPException, Request, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.security import hash_password, read_session, sign_session, verify_password
from app.config import Settings, get_settings
from app.database.models import User
from app.database.session import get_db
from app.web.dependencies import get_data_source

CSRF_COOKIE = "payroll_csrf"
CSRF_FORM_FIELD = "csrf_token"
CSRF_HEADER = "X-CSRF-Token"
CSRF_SALT = "payroll-web-csrf-v1"

# El modo demo no tiene filas en ``users``: la sesión firmada usa este id
# reservado y sólo se acepta cuando la fuente de datos es el store demo.
DEMO_USER_ID = -1

ROLE_LABELS = {
    "admin": "Administrador",
    "editor": "Editor",
    "viewer": "Solo lectura",
}

HTMX_REQUEST_HEADER = "HX-Request"
HTMX_REDIRECT_HEADER = "HX-Redirect"


@dataclass(frozen=True, slots=True)
class WebUser:
    """Identidad mínima que necesita la capa de presentación."""

    id: int
    email: str
    role: str
    is_demo: bool = False

    @property
    def display_name(self) -> str:
        if self.is_demo and self.role == "admin":
            return "Administrador"
        local_part = self.email.split("@", 1)[0]
        words = [word for word in re.split(r"[._-]+", local_part) if word]
        return " ".join(word.capitalize() for word in words) or self.email

    @property
    def initials(self) -> str:
        words = [word for word in re.split(r"[\s._-]+", self.display_name) if word]
        if not words:
            return "?"
        if len(words) == 1:
            return words[0][:2].upper()
        return (words[0][0] + words[1][0]).upper()

    @property
    def role_label(self) -> str:
        return ROLE_LABELS.get(self.role, self.role)


def _is_demo_source(data: Any) -> bool:
    return bool(getattr(data, "is_demo", False))


def _demo_user(settings: Settings, *, is_demo: bool = True) -> WebUser:
    return WebUser(
        id=DEMO_USER_ID,
        email=settings.admin_email.strip().lower(),
        role="admin",
        is_demo=is_demo,
    )


@lru_cache(maxsize=4)
def _demo_password_hash(password: str) -> str:
    """Hash PBKDF2 del admin demo, calculado una vez por proceso."""

    return hash_password(password)


def resolve_web_user(
    request: Request,
    db: Session,
    settings: Settings,
    data: Any,
) -> WebUser | None:
    """Resuelve la sesión web sin lanzar respuestas de error."""

    if not settings.web_auth_enabled:
        return _demo_user(settings, is_demo=_is_demo_source(data))

    token = request.cookies.get(settings.session_cookie)
    if not token:
        return None
    user_id = read_session(token, settings.secret_key, settings.session_max_age)
    if user_id is None:
        return None

    if _is_demo_source(data):
        if user_id == DEMO_USER_ID:
            return _demo_user(settings)
        return None

    user = db.get(User, user_id)
    if user is None or not user.active:
        return None
    return WebUser(id=user.id, email=user.email, role=user.role, is_demo=False)


def authenticate_web_user(
    *,
    email: str,
    password: str,
    db: Session,
    settings: Settings,
    data: Any,
) -> WebUser | None:
    """Valida credenciales del store demo o de la tabla ``users``."""

    normalized_email = email.strip().lower()
    if _is_demo_source(data):
        expected_email = settings.admin_email.strip().lower()
        password_hash = _demo_password_hash(settings.admin_password)
        password_ok = verify_password(password, password_hash)
        email_ok = hmac.compare_digest(normalized_email, expected_email)
        if email_ok and password_ok:
            return _demo_user(settings)
        return None

    user = db.scalar(select(User).where(User.email == normalized_email))
    if user is None or not user.active or not verify_password(password, user.password_hash):
        return None
    return WebUser(id=user.id, email=user.email, role=user.role, is_demo=False)


def require_web_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    data: Any = Depends(get_data_source),
) -> WebUser:
    """Dependencia de las rutas privadas: exige sesión o redirige a login."""

    request.state.web_settings = settings
    user = resolve_web_user(request, db, settings, data)
    if user is None:
        raise _authentication_required(request)
    request.state.web_user = user
    return user


def current_web_user(request: Request) -> WebUser:
    """Devuelve la identidad ya resuelta por la dependencia del router."""

    user = getattr(request.state, "web_user", None)
    if not isinstance(user, WebUser):
        raise _authentication_required(request)
    return user


def _is_htmx(request: Request) -> bool:
    return request.headers.get(HTMX_REQUEST_HEADER, "").strip().lower() == "true"


def _login_location(request: Request) -> str:
    next_path = request.url.path
    if request.url.query:
        next_path = f"{next_path}?{request.url.query}"
    login_path = request.url_for("login_page").path
    return f"{login_path}?{urlencode({'next': next_path})}"


def _authentication_required(request: Request) -> HTTPException:
    location = _login_location(request)
    if _is_htmx(request):
        return HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida",
            headers={HTMX_REDIRECT_HEADER: location},
        )
    return HTTPException(
        status_code=status.HTTP_303_SEE_OTHER,
        detail="Autenticación requerida",
        headers={"Location": location},
    )


def safe_next_url(value: str | None) -> str:
    """Acepta sólo rutas locales para evitar redirecciones abiertas."""

    candidate = (value or "").strip()
    if not candidate:
        return "/"
    if not candidate.startswith("/") or candidate.startswith("//"):
        return "/"
    if "\\" in candidate or any(ord(char) < 32 for char in candidate):
        return "/"
    parsed = urlsplit(candidate)
    if parsed.scheme or parsed.netloc:
        return "/"
    return candidate


def start_web_session(response: Any, user: WebUser, settings: Settings) -> None:
    """Emite la misma cookie firmada que usa ``POST /api/v1/auth/login``."""

    response.set_cookie(
        settings.session_cookie,
        sign_session(user.id, settings.secret_key),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def clear_web_session(response: Any, settings: Settings) -> None:
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.delete_cookie(
        CSRF_COOKIE,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


# ---------------------------------------------------------------------------
# CSRF: token firmado + cookie de doble submit
# ---------------------------------------------------------------------------


def _csrf_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt=CSRF_SALT)


def create_csrf_token(secret_key: str, user_id: int | None) -> str:
    return _csrf_serializer(secret_key).dumps({"uid": user_id, "nonce": secrets.token_urlsafe(16)})


def _read_csrf_token(token: str, settings: Settings) -> dict[str, Any] | None:
    try:
        payload = _csrf_serializer(settings.secret_key).loads(
            token, max_age=settings.session_max_age
        )
    except (BadSignature, SignatureExpired, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def csrf_token_for(request: Request, settings: Settings, user_id: int | None) -> str:
    """Reutiliza el token vigente o emite uno nuevo ligado a la identidad."""

    existing = request.cookies.get(CSRF_COOKIE)
    if existing:
        payload = _read_csrf_token(existing, settings)
        if payload is not None and payload.get("uid") == user_id:
            return existing
    return create_csrf_token(settings.secret_key, user_id)


def set_csrf_cookie(response: Any, token: str, settings: Settings) -> None:
    response.set_cookie(
        CSRF_COOKIE,
        token,
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


def validate_csrf(
    request: Request,
    submitted_token: str | None,
    settings: Settings,
    user_id: int | None,
) -> bool:
    if not settings.web_auth_enabled:
        return True
    cookie_token = request.cookies.get(CSRF_COOKIE)
    form_token = (submitted_token or request.headers.get(CSRF_HEADER) or "").strip()
    if not cookie_token or not form_token:
        return False
    if not hmac.compare_digest(cookie_token, form_token):
        return False
    payload = _read_csrf_token(form_token, settings)
    return payload is not None and payload.get("uid") == user_id


def enforce_csrf(
    request: Request,
    submitted_token: str | None,
    settings: Settings,
    user_id: int | None,
) -> None:
    if not validate_csrf(request, submitted_token, settings, user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Token CSRF inválido o ausente.",
        )


__all__ = [
    "CSRF_COOKIE",
    "CSRF_FORM_FIELD",
    "DEMO_USER_ID",
    "ROLE_LABELS",
    "WebUser",
    "authenticate_web_user",
    "clear_web_session",
    "create_csrf_token",
    "csrf_token_for",
    "current_web_user",
    "enforce_csrf",
    "require_web_user",
    "resolve_web_user",
    "safe_next_url",
    "set_csrf_cookie",
    "start_web_session",
    "validate_csrf",
]
