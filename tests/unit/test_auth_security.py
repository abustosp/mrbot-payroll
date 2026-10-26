from app.auth.security import hash_password, read_session, sign_session, verify_password


def test_password_hash_and_signed_session() -> None:
    password = "correct horse battery staple"
    hashed = hash_password(password)
    assert password not in hashed
    assert verify_password(password, hashed)
    assert not verify_password("wrong", hashed)

    token = sign_session(42, "unit-test-secret")
    assert read_session(token, "unit-test-secret", 60) == 42
    assert read_session(token, "different-secret", 60) is None
    assert read_session("malformed", "unit-test-secret", 60) is None
