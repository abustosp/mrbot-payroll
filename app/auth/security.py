from __future__ import annotations

import hashlib
import hmac
import math
import secrets
import time
from collections import deque
from collections.abc import Callable
from functools import lru_cache
from threading import Lock
from typing import Any

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PASSWORD_ROUNDS = 310_000
LOGIN_MAX_FAILURES = 5
LOGIN_WINDOW_SECONDS = 5 * 60
LOGIN_MAX_TRACKED_KEYS = 4096


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PASSWORD_ROUNDS)
    return f"pbkdf2_sha256${PASSWORD_ROUNDS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, rounds, salt, expected = stored.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds))
        return hmac.compare_digest(actual.hex(), expected)
    except (ValueError, TypeError):
        return False


@lru_cache(maxsize=1)
def dummy_password_hash() -> str:
    """Hash PBKDF2 descartable para igualar el costo cuando el email no existe.

    Se calcula una sola vez por proceso y su contraseña original se descarta:
    sólo sirve para que ``verify_password`` haga el mismo trabajo criptográfico
    en un login con email inexistente y no delate la existencia de la cuenta
    por diferencias de tiempo.
    """

    return hash_password(secrets.token_urlsafe(32))


class LoginAttemptLimiter:
    """Ventana deslizante de intentos fallidos de login por IP + email.

    shortcut: el estado vive en memoria y por proceso. No se comparte entre
    workers ni sobrevive reinicios, y la IP es la del socket directo (detrás de
    un proxy todos los clientes comparten la misma clave). Para despliegues con
    más de un proceso hace falta un almacén compartido, por ejemplo Redis.
    """

    def __init__(
        self,
        max_failures: int = LOGIN_MAX_FAILURES,
        window_seconds: int = LOGIN_WINDOW_SECONDS,
        *,
        clock: Callable[[], float] = time.monotonic,
        max_tracked_keys: int = LOGIN_MAX_TRACKED_KEYS,
    ) -> None:
        self._max_failures = max_failures
        self._window_seconds = window_seconds
        self._clock = clock
        self._max_tracked_keys = max_tracked_keys
        self._failures: dict[tuple[str, str], deque[float]] = {}
        self._lock = Lock()

    @staticmethod
    def _key(ip: str, email: str) -> tuple[str, str]:
        return (ip.strip() or "unknown", email.strip().lower())

    def _live_failures(self, key: tuple[str, str], now: float) -> deque[float] | None:
        """Devuelve la ventana vigente; sólo se llama con ``_lock`` tomado."""

        failures = self._failures.get(key)
        if failures is None:
            return None
        cutoff = now - self._window_seconds
        while failures and failures[0] <= cutoff:
            failures.popleft()
        if not failures:
            del self._failures[key]
            return None
        return failures

    def _trim(self) -> None:
        while len(self._failures) > self._max_tracked_keys:
            self._failures.pop(next(iter(self._failures)))

    def retry_after_seconds(self, ip: str, email: str) -> int:
        """Segundos restantes de bloqueo, o ``0`` si el intento está permitido."""

        now = self._clock()
        key = self._key(ip, email)
        with self._lock:
            failures = self._live_failures(key, now)
            if failures is None or len(failures) < self._max_failures:
                return 0
            return max(1, math.ceil(failures[0] + self._window_seconds - now))

    def record_failure(self, ip: str, email: str) -> None:
        now = self._clock()
        key = self._key(ip, email)
        with self._lock:
            failures = self._live_failures(key, now)
            if failures is None:
                failures = deque()
                self._failures[key] = failures
            failures.append(now)
            self._trim()

    def reset(self, ip: str, email: str) -> None:
        with self._lock:
            self._failures.pop(self._key(ip, email), None)

    def clear(self) -> None:
        """Vacía el estado; pensado para tests y reinicios controlados."""

        with self._lock:
            self._failures.clear()


login_attempts = LoginAttemptLimiter()


def session_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="payroll-session-v1")


def sign_session(user_id: int, secret_key: str, session_version: int = 1) -> str:
    return session_serializer(secret_key).dumps(
        {"user_id": user_id, "sv": session_version, "nonce": secrets.token_urlsafe(16)}
    )


def read_session_payload(token: str, secret_key: str, max_age: int) -> dict[str, Any] | None:
    try:
        payload = session_serializer(secret_key).loads(token, max_age=max_age)
        return payload if isinstance(payload, dict) else None
    except (BadSignature, SignatureExpired, TypeError):
        return None


def read_session_version(payload: dict[str, Any]) -> int | None:
    version = payload.get("sv", 1)
    return version if isinstance(version, int) and not isinstance(version, bool) and version >= 1 else None


def read_session(token: str, secret_key: str, max_age: int) -> int | None:
    payload = read_session_payload(token, secret_key, max_age)
    user_id = payload.get("user_id") if payload is not None else None
    return user_id if isinstance(user_id, int) else None
