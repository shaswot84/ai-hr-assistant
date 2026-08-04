from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select

from app.db.session import SessionLocal, init_db
from app.domain.identity import Department, Employee, Person
from app.domain.recruitment import Vacancy


def seed() -> None:
    """Idempotently seed the database with a demo manager and sample vacancy."""
    init_db()
    db = SessionLocal()
    try:
        now = datetime.now(UTC)

        dept_name = "Engineering"
        dept = db.scalar(select(Department).where(Department.name == dept_name))
        if dept is None:
            dept = Department(name=dept_name)
            db.add(dept)
            db.flush()

        # demo manager (HR_ADMIN)
        manager_email = "manager@example.com"
        manager_person = db.scalar(select(Person).where(Person.email == manager_email))
        if manager_person is None:
            manager_person = Person(
                first_name="Hiring",
                last_name="Manager",
                email=manager_email,
            )
            db.add(manager_person)
            db.flush()
        manager = db.scalar(
            select(Employee).where(Employee.person_id == manager_person.person_id)
        )
        if manager is None:
            manager = Employee(
                person_id=manager_person.person_id,
                employee_number="EMP-MGR-001",
            )
            db.add(manager)
            db.flush()

        # sample vacancy if none exist
        if db.scalar(select(Vacancy).limit(1)) is None:
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
        print("Seed complete: demo manager + sample vacancy ready.")
    finally:
        db.close()


if __name__ == "__main__":
    seed()
