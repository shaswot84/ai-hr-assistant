"""Test setup for the auth/recruitment unit suite."""

from __future__ import annotations

import os

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.contracts.auth import UserContext
from app.db.base import Base
from app.db.session import async_session_factory, engine
from app.domain import audit, conversation, leave, outbox, recruitment, setting  # noqa: F401
from app.domain.identity import (
    ApplicationUser,
    Candidate,
    Department,
    Designation,
    Employee,
    Person,
)
from app.shared.clock import get_clock


def _build_test_app() -> FastAPI:
    from app.api.routes import audit as audit_router
    from app.api.routes import auth as auth_router
    from app.api.routes import leave as leave_router
    from app.api.routes import people as people_router
    from app.api.routes import recruitment as recruitment_router
    from app.api.routes import settings as settings_router

    app = FastAPI()
    app.include_router(auth_router.router)
    app.include_router(audit_router.router)
    app.include_router(recruitment_router.router)
    app.include_router(settings_router.router)
    app.include_router(people_router.router)
    app.include_router(leave_router.router)
    return app


fastapi_app = _build_test_app()


@pytest.fixture(scope="session", autouse=True)
async def _schema():
    """Create all domain tables once for the test session, drop them after."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(autouse=True)
async def _clean_tables():
    """Truncate every table between tests so each test starts from empty."""
    yield
    async with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            await conn.execute(table.delete())


@pytest.fixture(autouse=True)
def _clean_settings_env_file():
    """Empty the throwaway settings .env file between tests for isolation."""
    yield
    path = os.environ["SETTINGS_ENV_FILE_PATH"]
    open(path, "w").close()


@pytest.fixture()
async def db():
    """An AsyncSession bound to the test SQLite file."""
    async with async_session_factory() as session:
        yield session


@pytest.fixture()
def client():
    """A FastAPI TestClient (runs the app's lifespan, same DB as `db`)."""
    with TestClient(fastapi_app) as c:
        yield c


async def _seed_person(db: AsyncSession, *, email: str, first: str, last: str) -> Person:
    now = get_clock().now()
    person = Person(first_name=first, last_name=last, email=email, created_at=now, updated_at=now)
    db.add(person)
    await db.flush()
    return person


async def _seed_app_user(db: AsyncSession, *, person: Person, subject: str, role: str, password: str) -> ApplicationUser:
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
    await db.flush()
    return app_user


@pytest.fixture()
def manager_password() -> str:
    return "manager-secret-1"


@pytest.fixture()
async def manager_context(db: AsyncSession, manager_password: str) -> UserContext:
    """Seed a full manager identity (Person/Employee/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = await _seed_person(db, email="manager@acme-hr-test.dev", first="Hiring", last="Manager")
    dept = Department(name="Human Resources")
    db.add(dept)
    await db.flush()
    designation = Designation(department_id=dept.department_id, title="HR Manager")
    db.add(designation)
    await db.flush()
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
    await _seed_app_user(db, person=person, subject="mgr-subject", role="HR_ADMIN", password=manager_password)
    await db.commit()
    return UserContext(
        subject="mgr-subject", email=person.email, display_name="Hiring Manager", coarse_role="HR_ADMIN"
    )


@pytest.fixture()
def employee_password() -> str:
    return "employee-secret-1"


@pytest.fixture()
async def employee_context(db: AsyncSession, employee_password: str) -> UserContext:
    """Seed a full employee identity (Person/Employee/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = await _seed_person(db, email="employee@acme-hr-test.dev", first="Sam", last="Staff")
    dept = Department(name="Engineering")
    db.add(dept)
    await db.flush()
    designation = Designation(department_id=dept.department_id, title="Engineer")
    db.add(designation)
    await db.flush()
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
    await _seed_app_user(db, person=person, subject="emp-subject", role="EMPLOYEE", password=employee_password)
    await db.commit()
    return UserContext(
        subject="emp-subject", email=person.email, display_name="Sam Staff", coarse_role="EMPLOYEE"
    )


@pytest.fixture()
def candidate_password() -> str:
    return "candidate-secret-1"


@pytest.fixture()
async def candidate_context(db: AsyncSession, candidate_password: str) -> UserContext:
    """Seed a full candidate identity (Person/Candidate/ApplicationUser) and return its UserContext."""
    now = get_clock().now()
    person = await _seed_person(db, email="candidate@acme-hr-test.dev", first="Alex", last="Applicant")
    db.add(
        Candidate(
            person_id=person.person_id,
            registration_date=get_clock().today(),
            created_at=now,
            updated_at=now,
        )
    )
    await _seed_app_user(
        db, person=person, subject="cand-subject", role="CANDIDATE", password=candidate_password
    )
    await db.commit()
    return UserContext(
        subject="cand-subject", email=person.email, display_name="Alex Applicant", coarse_role="CANDIDATE"
    )

