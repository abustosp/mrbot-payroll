from app.auth.security import (
    LoginAttemptLimiter,
    dummy_password_hash,
    hash_password,
    read_session,
    read_session_payload,
    read_session_version,
    sign_session,
    verify_password,
)


def test_password_hash_and_signed_session() -> None:
    password = "correct horse battery staple"
    hashed = hash_password(password)
    assert password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)

    token = sign_session(42, "unit-test-secret")
    payload = read_session_payload(token, "unit-test-secret", 60)
    assert payload is not None
    assert payload["sv"] == 1
    assert read_session_version(payload) == 1
    assert read_session(token, "unit-test-secret", 60) == 42
    assert read_session(token, "different-secret", 60) is None
    assert read_session("malformed", "unit-test-secret", 60) is None


def test_signed_session_token_rotates_between_emissions() -> None:
    first = sign_session(42, "unit-test-secret", session_version=2)
    second = sign_session(42, "unit-test-secret", session_version=2)

    assert first != second
    assert read_session(first, "unit-test-secret", 60) == 42
    assert read_session(second, "unit-test-secret", 60) == 42
    payload = read_session_payload(first, "unit-test-secret", 60)
    assert payload is not None
    assert read_session_version(payload) == 2


def test_dummy_password_hash_is_a_valid_pbkdf2_hash() -> None:
    dummy = dummy_password_hash()

    assert dummy.startswith("pbkdf2_sha256$")
    assert dummy_password_hash() is dummy
    assert not verify_password("", dummy)


def test_login_attempt_limiter_blocks_within_window_and_expires() -> None:
    now = [1_000.0]
    limiter = LoginAttemptLimiter(max_failures=2, window_seconds=60, clock=lambda: now[0])

    assert limiter.retry_after_seconds("127.0.0.1", "user@example.test") == 0
    limiter.record_failure("127.0.0.1", "user@example.test")
    assert limiter.retry_after_seconds("127.0.0.1", "USER@example.test") == 0
    limiter.record_failure("127.0.0.1", "user@example.test")

    assert limiter.retry_after_seconds("127.0.0.1", "user@example.test") > 0
    assert limiter.retry_after_seconds("127.0.0.2", "user@example.test") == 0
    assert limiter.retry_after_seconds("127.0.0.1", "other@example.test") == 0

    now[0] += 61
    assert limiter.retry_after_seconds("127.0.0.1", "user@example.test") == 0


def test_login_attempt_limiter_reset_clears_failures() -> None:
    limiter = LoginAttemptLimiter(max_failures=1, window_seconds=60)
    limiter.record_failure("127.0.0.1", "user@example.test")
    assert limiter.retry_after_seconds("127.0.0.1", "user@example.test") > 0

    limiter.reset("127.0.0.1", "user@example.test")
    assert limiter.retry_after_seconds("127.0.0.1", "user@example.test") == 0
