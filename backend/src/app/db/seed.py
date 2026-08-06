from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select

from app.auth.passwords import hash_password
from app.db.sync_session import SessionLocal, init_db
from app.domain.identity import (
    ApplicationUser,
    Candidate,
    Department,
    Designation,
    Employee,
    Person,
)
from app.domain.recruitment import Vacancy
from app.shared.clock import get_clock


def _get_or_create_department(db, name: str) -> Department:
    """Return the department matching `name`, creating it if it does not yet exist."""
    dept = db.scalar(select(Department).where(Department.name == name))
    if dept is None:
        dept = Department(name=name)
        db.add(dept)
        db.flush()
    return dept


def _get_or_create_designation(db, department: Department, title: str) -> Designation:
    """Return the designation matching (department, title), creating it if needed."""
    stmt = select(Designation).where(
        Designation.department_id == department.department_id, Designation.title == title
    )
    designation = db.scalar(stmt)
    if designation is None:
        designation = Designation(department_id=department.department_id, title=title)
        db.add(designation)
        db.flush()
    return designation


def _provision_user(
    db,
    *,
    email: str,
    first: str,
    last: str,
    password: str,
    role: str,
    department: Department | None = None,
    designation: Designation | None = None,
    employee_code: str | None = None,
) -> None:
    """Idempotently create the Person + ApplicationUser (+ Employee/Candidate) for a demo user."""
    clock = get_clock()
    now = clock.now()

    person = db.scalar(select(Person).where(Person.email == email))
    if person is None:
        person = Person(first_name=first, last_name=last, email=email, created_at=now, updated_at=now)
        db.add(person)
        db.flush()

    app_user = db.scalar(
        select(ApplicationUser).where(
            ApplicationUser.identity_provider == "local", ApplicationUser.person_id == person.person_id
        )
    )
    if app_user is None:
        app_user = ApplicationUser(
            external_subject=str(uuid.uuid4()),
            person_id=person.person_id,
            coarse_role=role,
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
        )
        db.add(app_user)
        db.flush()
    elif not app_user.password_hash:
        app_user.password_hash = hash_password(password)

    if role == "CANDIDATE":
        if db.scalar(select(Candidate).where(Candidate.person_id == person.person_id)) is None:
            db.add(
                Candidate(
                    person_id=person.person_id,
                    registration_date=clock.today(),
                    created_at=now,
                    updated_at=now,
                )
            )
    elif role in ("HR_ADMIN", "EMPLOYEE") and (
        db.scalar(select(Employee).where(Employee.person_id == person.person_id)) is None
    ):
        if department is None or designation is None:
            raise ValueError("department and designation are required to seed an employee.")
        db.add(
            Employee(
                person_id=person.person_id,
                employee_code=employee_code or f"EMP-{uuid.uuid4().hex[:8].upper()}",
                department_id=department.department_id,
                designation_id=designation.designation_id,
                joining_date=clock.today(),
                created_at=now,
                updated_at=now,
            )
        )


def seed() -> None:
    """Idempotently seed the database with demo users and a sample vacancy."""
    init_db()
    db = SessionLocal()
    try:
        clock = get_clock()
        now = clock.now()

        hr_dept = _get_or_create_department(db, "Human Resources")
        hr_manager_designation = _get_or_create_designation(db, hr_dept, "HR Manager")
        eng_dept = _get_or_create_department(db, "Engineering")

        _provision_user(
            db,
            email="manager@example.com",
            first="Hiring",
            last="Manager",
            password="manager123",
            role="HR_ADMIN",
            department=hr_dept,
            designation=hr_manager_designation,
            employee_code="EMP-MGR-001",
        )
        _provision_user(
            db,
            email="candidate@example.com",
            first="Alex",
            last="Applicant",
            password="candidate123",
            role="CANDIDATE",
        )

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
                    department_id=eng_dept.department_id,
                    description=(
                        "We're hiring a Senior Backend Engineer to design and build scalable "
                        "APIs. Requirements: Python, FastAPI, PostgreSQL, Docker, Kubernetes, "
                        "AWS, and mentoring junior engineers."
                    ),
                    employment_type="FULL_TIME",
                    opening_date=clock.today(),
                    closing_date=clock.today() + timedelta(days=30),
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
