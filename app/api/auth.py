# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.schemas import LoginInput, UserRead
from app.auth.dependencies import require_user
from app.auth.security import sign_session, verify_password
from app.config import Settings, get_settings
from app.database.models import User
from app.database.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=UserRead)
def login(
    payload: LoginInput,
    response: Response,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    user = db.scalar(select(User).where(User.email == payload.email.strip().lower()))
    if user is None or not user.active or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Credenciales inválidas")
    response.set_cookie(
        settings.session_cookie,
        sign_session(user.id, settings.secret_key),
        max_age=settings.session_max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    return user


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
