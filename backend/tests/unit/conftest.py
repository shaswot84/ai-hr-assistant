from __future__ import annotations

import os

# Configure an in-memory SQLite backend BEFORE importing the app, since the
# global engine is created at module import time.
os.environ["DATABASE_URL"] = "sqlite://"
os.environ["MINIO_ENDPOINT"] = "127.0.0.1:1"  # refuse fast; avoid DNS wait on 'minio'
os.environ["MINIO_AUTO_INIT"] = "false"  # skip bucket setup in lifespan

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

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
    c.post(
        "/api/auth/dev-login",
        json={"role": "CANDIDATE", "email": "cand@example.com", "name": "Alex Applicant"},
    )
    yield c
    app.dependency_overrides.clear()
    c.close()


@pytest.fixture
def manager_client():
    c = TestClient(app)
    app.dependency_overrides[get_db] = lambda: TestingSessionLocal()
    c.post(
        "/api/auth/dev-login",
        json={"role": "HR_ADMIN", "email": "mgr@example.com", "name": "Hiring Manager"},
    )
    yield c
    app.dependency_overrides.clear()
    c.close()
