from __future__ import annotations

from fastapi.testclient import TestClient

from app.auth.passwords import hash_password, verify_password
from app.auth.jwt import JwtAuthProvider
from app.config.settings import get_settings
from app.db.session import get_db
from app.domain.identity import ApplicationUser, Employee, Person
from app.main import app


def test_health(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_me_unauthenticated(client):
    res = client.get("/api/auth/me")
    assert res.status_code == 401


def test_me_authenticated(client):
    res = client.get(
        "/api/auth/me",
        headers={
            "x-test-subject": "user_abc",
            "x-test-role": "EMPLOYEE",
            "x-test-email": "a@b.com",
            "x-test-name": "Alice",
        },
    )
    assert res.status_code == 200
    body = res.json()
    assert body["user"]["coarse_role"] == "EMPLOYEE"
    assert body["user"]["email"] == "a@b.com"


def test_wrong_role_forbidden(client):
    res = client.post(
        "/api/vacancies",
        headers={"x-test-subject": "u1", "x-test-role": "CANDIDATE"},
        json={"title": "X", "department_name": "Eng", "employment_type": "FULL_TIME"},
    )
    assert res.status_code == 403


def test_password_hash_roundtrip():
    stored = hash_password("correct horse battery staple")
    assert stored.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", stored)
    assert not verify_password("wrong password", stored)
    assert not verify_password("", "garbage" * 10)


def test_login_rejects_bad_credentials(db_session):
    person = Person(first_name="Login", last_name="User", email="login@example.com")
    db_session.add(person)
    db_session.flush()
    db_session.add(
        ApplicationUser(
            external_subject="jwt-sub-1",
            person_id=person.person_id,
            coarse_role="CANDIDATE",
            password_hash=hash_password("secret123"),
        )
    )
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            res = c.post("/api/auth/login", json={"email": "login@example.com", "password": "wrong"})
            assert res.status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_login_returns_token_and_user_authorizes(db_session):
    person = Person(first_name="Hiring", last_name="Manager", email="hr@example.com")
    db_session.add(person)
    db_session.flush()
    db_session.add(
        ApplicationUser(
            external_subject="sub-hr",
            person_id=person.person_id,
            coarse_role="HR_ADMIN",
            password_hash=hash_password("adminpass"),
        )
    )
    db_session.add(
        Employee(person_id=person.person_id, employee_number="EMP-HR-001")
    )
    db_session.commit()

    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    try:
        with TestClient(app) as c:
            res = c.post("/api/auth/login", json={"email": "hr@example.com", "password": "adminpass"})
            assert res.status_code == 200
            body = res.json()
            token = body["access_token"]
            assert body["token_type"] == "bearer"
            assert body["user"]["coarse_role"] == "HR_ADMIN"

            # decoded token subject matches the user's external_subject
            payload = JwtAuthProvider()._decode(token)
            assert payload["sub"] == "sub-hr"

            me = c.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
            assert me.status_code == 200
            assert me.json()["user"]["email"] == "hr@example.com"

            # the HR_ADMIN token passes the recruitment authorization check
            vac = c.post(
                "/api/vacancies",
                headers={"Authorization": f"Bearer {token}"},
                json={"title": "SDE", "department_name": "Eng", "employment_type": "FULL_TIME"},
            )
            assert vac.status_code == 201
    finally:
        app.dependency_overrides.clear()