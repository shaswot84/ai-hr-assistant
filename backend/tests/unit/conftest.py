"""Test setup for the auth/recruitment unit suite.

The test-wide environment (SQLite ``DATABASE_URL``, JWT secret, MinIO
auto-init) is bootstrapped in ``tests/conftest.py`` before any app module can
be imported. This conftest wires the auth/recruitment routers to a throwaway
SQLite file and provides per-test database/client fixtures.

Scope: only what `test_auth.py`/`test_recruitment.py` exercise (auth +
recruitment). `app.knowledge` (pgvector-backed RAG models) is never imported
here, so `Base.metadata` only contains the domain tables when
`create_all()` runs — importing `app.knowledge.models` would pull in
Postgres-only `Vector` columns that SQLite can't create.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.passwords import hash_password
from app.contracts.auth import UserContext
from app.db.base import Base
from app.db.sync_session import SessionLocal, engine
from app.domain import audit, outbox, recruitment, setting  # noqa: F401
from app.domain.identity import (
    ApplicationUser,
    Candidate,
    Department,
    Designation,
    Employee,
    Person,
)
from app.shared.clock import get_clock


# A purpose-built app with only the routers this suite exercises — not the
# real `app.main:app`. That app also wires up `app.api.knowledge`, which
# imports `db/session.py`'s *async* engine at module load time; that engine
# reads the same DATABASE_URL as the sync engine above, and a sqlite:// URL
# (fine for the sync engine) isn't a valid async driver, so importing the
# full app here would crash collection. Knowledge/RAG has its own test suite
# with its own (Postgres-backed) fixtures — out of scope for this one.
def _build_test_app() -> FastAPI:
    from app.api.routes import auth as auth_router
    from app.api.routes import people as people_router
    from app.api.routes import recruitment as recruitment_router
    from app.api.routes import settings as settings_router

    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(recruitment_router.router)
    app.include_router(settings_router.router)
    app.include_router(people_router.router)
    return app


fastapi_app = _build_test_app()


@pytest.fixture(scope="session", autouse=True)
def _schema():
    """Create all domain tables once for the test session, drop them after."""
    Base.metadata.create_all(bind=engine)
    yield
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture(autouse=True)
def _clean_tables():
    """Truncate every table between tests so each test starts from empty."""
    yield
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())


@pytest.fixture()
def db():
    """A sync DB session bound to the test SQLite file."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client():
    """A FastAPI TestClient (runs the app's lifespan, same DB as `db`)."""
    with TestClient(fastapi_app) as c:
        yield c


def _seed_person(db, *, email: str, first: str, last: str) -> Person:
    now = get_clock().now()
    person = Person(first_name=first, last_name=last, email=email, created_at=now, updated_at=now)
    db.add(person)
    db.flush()
    return person


def _seed_app_user(db, *, person: Person, subject: str, role: str, password: str) -> ApplicationUser:
    now = get_clock().now()
    app_user = ApplicationUser(
        external_subject=subject,
        person_id=person.person_id,
        coarse_role=role,
        password_hash=hash_password(password),
        created_at=now,
        updated_at=now,
    )
    db.add(app_user)
    db.flush()
    return app_user


@pytest.fixture()
def manager_password() -> str:
    return "manager-secret-1"


@pytest.fixture()
def manager_context(db, manager_password) -> UserContext:
    """Seed a full manager identity (Person/Employee/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = _seed_person(db, email="manager@acme-hr-test.dev", first="Hiring", last="Manager")
    dept = Department(name="Human Resources")
    db.add(dept)
    db.flush()
    designation = Designation(department_id=dept.department_id, title="HR Manager")
    db.add(designation)
    db.flush()
    db.add(
        Employee(
            person_id=person.person_id,
            employee_code="EMP-TEST-MGR",
            department_id=dept.department_id,
            designation_id=designation.designation_id,
            joining_date=get_clock().today(),
            created_at=now,
            updated_at=now,
        )
    )
    _seed_app_user(db, person=person, subject="mgr-subject", role="HR_ADMIN", password=manager_password)
    db.commit()
    return UserContext(
        subject="mgr-subject", email=person.email, display_name="Hiring Manager", coarse_role="HR_ADMIN"
    )


@pytest.fixture()
def employee_password() -> str:
    return "employee-secret-1"


@pytest.fixture()
def employee_context(db, employee_password) -> UserContext:
    """Seed a full employee identity (Person/Employee/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = _seed_person(db, email="employee@acme-hr-test.dev", first="Sam", last="Staff")
    dept = Department(name="Engineering")
    db.add(dept)
    db.flush()
    designation = Designation(department_id=dept.department_id, title="Engineer")
    db.add(designation)
    db.flush()
    db.add(
        Employee(
            person_id=person.person_id,
            employee_code="EMP-TEST-001",
            department_id=dept.department_id,
            designation_id=designation.designation_id,
            joining_date=get_clock().today(),
            created_at=now,
            updated_at=now,
        )
    )
    _seed_app_user(db, person=person, subject="emp-subject", role="EMPLOYEE", password=employee_password)
    db.commit()
    return UserContext(
        subject="emp-subject", email=person.email, display_name="Sam Staff", coarse_role="EMPLOYEE"
    )


@pytest.fixture()
def candidate_password() -> str:
    return "candidate-secret-1"


@pytest.fixture()
def candidate_context(db, candidate_password) -> UserContext:
    """Seed a full candidate identity (Person/Candidate/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = _seed_person(db, email="candidate@acme-hr-test.dev", first="Alex", last="Applicant")
    db.add(
        Candidate(
            person_id=person.person_id,
            registration_date=get_clock().today(),
            created_at=now,
            updated_at=now,
        )
    )
    _seed_app_user(
        db, person=person, subject="cand-subject", role="CANDIDATE", password=candidate_password
    )
    db.commit()
    return UserContext(
        subject="cand-subject", email=person.email, display_name="Alex Applicant", coarse_role="CANDIDATE"
    )
