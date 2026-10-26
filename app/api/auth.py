# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import ChangePasswordInput, LoginInput, UserRead
from app.auth.dependencies import require_user
from app.auth.security import (
    dummy_password_hash,
    hash_password,
    login_attempts,
    sign_session,
    verify_password,
)
from app.config import Settings, get_settings
from app.database.models import User
from app.database.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str:
    return request.client.host if request.client is not None else "unknown"


def _set_session_cookie(response: Response, user_id: int, settings: Settings) -> None:
    response.set_cookie(
        settings.session_cookie,
        sign_session(user_id, settings.secret_key),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )


@router.post("/login", response_model=UserRead)
def login(
    payload: LoginInput,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    email = payload.email.strip().lower()
    client_ip = _client_ip(request)
    retry_after = login_attempts.retry_after_seconds(client_ip, email)
    if retry_after:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Demasiados intentos fallidos. Intente nuevamente más tarde.",
            headers={"Retry-After": str(retry_after)},
        )

    user = db.scalar(select(User).where(User.email == email))
    # Verificar siempre un hash PBKDF2, incluso sin usuario, para no filtrar la
    # existencia de la cuenta por diferencias de tiempo.
    stored_hash = user.password_hash if user is not None else dummy_password_hash()
    password_ok = verify_password(payload.password, stored_hash)
    if user is None or not user.active or not password_ok:
        login_attempts.record_failure(client_ip, email)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas"
        )

    login_attempts.reset(client_ip, email)
    _set_session_cookie(response, user.id, settings)
    return user


@router.post("/change-password", status_code=status.HTTP_204_NO_CONTENT)
def change_password(
    payload: ChangePasswordInput,
    response: Response,
    user: User = Depends(require_user),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La contraseña actual es incorrecta",
        )
    if payload.new_password == payload.current_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="La nueva contraseña debe ser distinta de la actual",
        )

    user.password_hash = hash_password(payload.new_password)
    db.add(user)
    db.commit()
    # La cookie se reemite con un nonce nuevo: rotación efectiva del token.
    _set_session_cookie(response, user.id, settings)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(response: Response, settings: Settings = Depends(get_settings)):
    response.delete_cookie(
        settings.session_cookie,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )


@router.get("/me", response_model=UserRead)
def me(user: User = Depends(require_user)):
    return user
