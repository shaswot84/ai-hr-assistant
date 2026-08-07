from __future__ import annotations

from app.auth.passwords import hash_password, verify_password


def test_hash_and_verify_password_roundtrip():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("correct horse battery staple", hashed) is True


def test_verify_password_rejects_wrong_password():
    hashed = hash_password("correct horse battery staple")
    assert verify_password("wrong password", hashed) is False


def test_verify_password_rejects_garbage_hash():
    assert verify_password("anything", "not-a-real-hash") is False


def test_login_success_returns_token_and_user(client, manager_context, manager_password):
    res = client.post(
        "/api/auth/login", json={"email": manager_context.email, "password": manager_password}
    )
    assert res.status_code == 200
    body = res.json()
    assert body["access_token"]
    assert body["user"]["coarse_role"] == "HR_ADMIN"
    assert body["user"]["email"] == manager_context.email


def test_login_wrong_password_is_generic_401(client, manager_context):
    res = client.post(
        "/api/auth/login", json={"email": manager_context.email, "password": "not-the-password"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password."


def test_login_unknown_email_is_the_same_generic_401(client):
    res = client.post(
        "/api/auth/login", json={"email": "nobody@acme-hr-test.dev", "password": "whatever"}
    )
    assert res.status_code == 401
    assert res.json()["detail"] == "Invalid email or password."


def test_me_requires_authentication(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_returns_current_user_for_valid_token(client, manager_context, manager_password):
    login = client.post(
        "/api/auth/login", json={"email": manager_context.email, "password": manager_password}
    )
    token = login.json()["access_token"]
    res = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    assert res.json()["user"]["email"] == manager_context.email


def test_me_rejects_garbage_token(client):
    res = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-jwt"})
    assert res.status_code == 401
