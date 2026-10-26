from __future__ import annotations

import hashlib
import hmac
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

PASSWORD_ROUNDS = 310_000


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


def session_serializer(secret_key: str) -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(secret_key, salt="payroll-session-v1")


def sign_session(user_id: int, secret_key: str) -> str:
    return session_serializer(secret_key).dumps({"user_id": user_id})


def read_session(token: str, secret_key: str, max_age: int) -> int | None:
    try:
        payload = session_serializer(secret_key).loads(token, max_age=max_age)
        user_id = payload.get("user_id")
        return user_id if isinstance(user_id, int) else None
    except (BadSignature, SignatureExpired, TypeError):
        return None
