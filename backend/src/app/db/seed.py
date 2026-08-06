from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db.session import SessionLocal, init_db
from app.domain.identity import ApplicationUser, Candidate, Department, Employee, Person
from app.domain.recruitment import Vacancy


def _provision_user(
    db,
    email: str,
    first: str,
    last: str,
    password: str,
    role: str,
    employee_number: str | None = None,
) -> None:
    """Idempotently create the Person + ApplicationUser (, Employee/Candidate) for a demo user."""
    person = db.scalar(select(Person).where(Person.email == email))
    if person is None:
        person = Person(first_name=first, last_name=last, email=email)
        db.add(person)
        db.flush()

    app_user = db.scalar(select(ApplicationUser).where(ApplicationUser.person_id == person.person_id))
    if app_user is None:
        app_user = ApplicationUser(
            external_subject=str(uuid.uuid4()),
            person_id=person.person_id,
            coarse_role=role,
            password_hash=hash_password(password),
        )
        db.add(app_user)
        db.flush()
    elif not app_user.password_hash:
        app_user.password_hash = hash_password(password)

    if role == "CANDIDATE":
        if db.scalar(select(Candidate).where(Candidate.person_id == person.person_id)) is None:
            db.add(Candidate(person_id=person.person_id, registration_date=date.today()))
    elif role in ("HR_ADMIN", "EMPLOYEE") and (
        db.scalar(select(Employee).where(Employee.person_id == person.person_id)) is None
    ):
        db.add(
                Employee(
                    person_id=person.person_id,
                    employee_number=employee_number or f"EMP-{uuid.uuid4().hex[:8].upper()}",
                )
            )


def seed() -> None:
    """Idempotently seed the database with demo users and a sample vacancy."""
    init_db()
    db = SessionLocal()
    try:
        # demo users (login via the JWT login endpoint)
        _provision_user(db, "manager@example.com", "Hiring", "Manager", "manager123", "HR_ADMIN", "EMP-MGR-001")
        _provision_user(db, "candidate@example.com", "Alex", "Applicant", "candidate123", "CANDIDATE")
        now = datetime.now(UTC)

        dept_name = "Engineering"
        dept = db.scalar(select(Department).where(Department.name == dept_name))
        if dept is None:
            dept = Department(name=dept_name)
            db.add(dept)
            db.flush()

        manager = db.scalar(
            select(Employee)
            .join(Person, Employee.person_id == Person.person_id)
            .where(Person.email == "manager@example.com")
        )

        # sample vacancy if none exist
        if db.scalar(select(Vacancy).limit(1)) is None and manager is not None:
            db.add(
                Vacancy(
                    title="Senior Backend Engineer",
                    department_id=dept.department_id,
                    description=(
                        "We're hiring a Senior Backend Engineer to design and build scalable "
                        "APIs. Requirements: Python, FastAPI, PostgreSQL, Docker, Kubernetes, "
                        "AWS, and mentoring junior engineers."
                    ),
                    employment_type="FULL_TIME",
                    opening_date=date.today(),
                    closing_date=date.today() + timedelta(days=30),
                    created_by_employee_id=manager.employee_id,
                    approval_status="APPROVED",
                    status="OPEN",
                    created_at=now,
                    updated_at=now,
                )
            )

        db.commit()
        print("Seed complete: demo manager + candidate + sample vacancy ready.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
