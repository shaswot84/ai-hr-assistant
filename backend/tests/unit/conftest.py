from __future__ import annotations

import os

# Configure an in-memory SQLite backend BEFORE importing the app, since the
# global engine is created at module import time.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["MINIO_ENDPOINT"] = "127.0.0.1:1"  # refuse fast; avoid DNS wait on 'minio'
os.environ["MINIO_AUTO_INIT"] = "false"  # skip bucket setup in lifespan
os.environ["JWT_SECRET_KEY"] = "test-secret-key"  # robust JWT for provider tests
os.environ["AUTH_PROVIDER"] = "jwt"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.deps import get_auth_provider
from app.auth.provider import AuthProvider
from app.contracts.auth import UserContext
from app.db.base import Base
from app.db.session import get_db
from app.main import app

# in-memory SQLite for tests (StaticPool so each connection sees the same DB)
engine = create_engine(
    "sqlite://",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


class HeaderAuthProvider(AuthProvider):
    """Test-only AuthProvider that reads identity from per-request headers.

    Lives in the test suite (never shipped) so each TestClient can carry its
    own role without a global dependency override colliding across fixtures.
    """

    name = "test_headers"

    def authenticate(self, request) -> UserContext | None:
        subject = request.headers.get("x-test-subject")
        role = request.headers.get("x-test-role")
        if not subject or not role:
            return None
        return UserContext(
            subject=subject,
            email=request.headers.get("x-test-email", f"{subject}@example.com"),
            display_name=request.headers.get("x-test-name", subject),
            coarse_role=role,
        )

    def build_login_url(self, redirect_uri: str) -> str | None:
        return None

    def exchange_code(self, code: str, redirect_uri: str) -> UserContext:
        raise NotImplementedError

    def build_logout_url(self, redirect_uri: str) -> str | None:
        return None


@pytest.fixture(autouse=True)
def _fresh_db():
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db_session():
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


def _make_client():
    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[get_auth_provider] = lambda: HeaderAuthProvider()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    yield from _make_client()


@pytest.fixture
def candidate_client():
    c = TestClient(app)
    app.dependency_overrides[get_db] = lambda: TestingSessionLocal()
    app.dependency_overrides[get_auth_provider] = lambda: HeaderAuthProvider()
    c.headers.update(
        {
            "x-test-subject": "cand-jwtsub",
            "x-test-role": "CANDIDATE",
            "x-test-email": "cand@example.com",
            "x-test-name": "Alex Applicant",
        }
    )
    yield c
    app.dependency_overrides.clear()
    c.close()


@pytest.fixture
def manager_client():
    c = TestClient(app)
    app.dependency_overrides[get_db] = lambda: TestingSessionLocal()
    app.dependency_overrides[get_auth_provider] = lambda: HeaderAuthProvider()
    c.headers.update(
        {
            "x-test-subject": "mgr-jwtsub",
            "x-test-role": "HR_ADMIN",
            "x-test-email": "mgr@example.com",
            "x-test-name": "Hiring Manager",
        }
    )
    yield c
    app.dependency_overrides.clear()
    c.close()
