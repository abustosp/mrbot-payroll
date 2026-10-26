# ruff: noqa: B008 -- FastAPI resolves Depends defaults at request time.
from collections.abc import Callable

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.auth.security import read_session_payload, read_session_version
from app.config import Settings, get_settings
from app.database.models import User
from app.database.session import get_db


def require_user(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    token = request.cookies.get(settings.session_cookie)
    payload = read_session_payload(token, settings.secret_key, settings.session_max_age) if token else None
    user_id = payload.get("user_id") if payload is not None else None
    session_version = read_session_version(payload) if payload is not None else None
    user = db.get(User, user_id) if isinstance(user_id, int) and session_version is not None else None
    if user is None or not user.active or user.session_version != session_version:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Autenticación requerida")
    return user


def require_role(*roles: str) -> Callable:
    def check_role(user: User = Depends(require_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Permiso insuficiente")
        return user

    return check_role
