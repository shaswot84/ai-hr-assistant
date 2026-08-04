from __future__ import annotations

import io


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_me_unauthenticated(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_dev_login_and_me(client):
    login = client.post("/api/auth/dev-login", json={"role": "CANDIDATE", "email": "a@b.com"})
    assert login.status_code == 200
    assert login.json()["user"]["coarse_role"] == "CANDIDATE"

    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["coarse_role"] == "CANDIDATE"
    assert me.json()["user"]["email"] == "a@b.com"


def test_invalid_role_rejected(client):
    res = client.post("/api/auth/dev-login", json={"role": "SUPERUSER"})
    assert res.status_code == 400
