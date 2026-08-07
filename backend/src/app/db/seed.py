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

# (title, department, employment_type, description, days_open) — a spread of
# roles/departments so the candidate portal and AI scoring demo have variety.
SAMPLE_VACANCIES = [
    (
        "Senior Backend Engineer",
        "Engineering",
        "FULL_TIME",
        (
            "We're hiring a Senior Backend Engineer to design and build scalable APIs. "
            "Requirements: Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, and "
            "mentoring junior engineers."
        ),
        30,
    ),
    (
        "Senior Frontend Engineer",
        "Engineering",
        "FULL_TIME",
        (
            "We're hiring a Senior Frontend Engineer with 5+ years of experience in React, "
            "TypeScript, and modern state management (Redux/Zustand). You'll lead frontend "
            "architecture decisions, mentor junior engineers, own performance optimization "
            "and accessibility, and collaborate with design and backend teams. Experience "
            "with Next.js, component design systems, and CI/CD pipelines is required."
        ),
        21,
    ),
    (
        "DevOps Engineer",
        "Engineering",
        "FULL_TIME",
        (
            "Looking for a DevOps Engineer to own our cloud infrastructure. Requirements: "
            "Kubernetes, Terraform, AWS, CI/CD pipelines (GitHub Actions), Docker, "
            "observability (Prometheus/Grafana), and on-call incident response experience."
        ),
        30,
    ),
    (
        "Product Designer",
        "Design",
        "FULL_TIME",
        (
            "We're looking for a Product Designer with strong Figma, prototyping, and user "
            "research skills. Experience with design systems and cross-functional "
            "collaboration with engineering is a must."
        ),
        21,
    ),
    (
        "Data Analyst",
        "Data",
        "FULL_TIME",
        (
            "Seeking a Data Analyst to turn raw data into decisions. Requirements: SQL, "
            "Python (pandas), dashboarding (Looker/Tableau/Metabase), A/B test analysis, "
            "and clear written communication with non-technical stakeholders."
        ),
        30,
    ),
    (
        "HR Generalist",
        "Human Resources",
        "FULL_TIME",
        (
            "Join our People team as an HR Generalist covering recruitment coordination, "
            "onboarding, employee relations, and policy administration. Requirements: 2+ "
            "years HR experience, HRIS familiarity, and strong interpersonal skills."
        ),
        30,
    ),
    (
        "Marketing Manager",
        "Marketing",
        "FULL_TIME",
        (
            "We need a Marketing Manager to own campaign strategy across paid, content, and "
            "lifecycle channels. Requirements: 4+ years B2B/B2C marketing, analytics tools "
            "(GA4/Mixpanel), budget management, and experience briefing design/content teams."
        ),
        21,
    ),
    (
        "Customer Support Specialist",
        "Operations",
        "PART_TIME",
        (
            "Part-time Customer Support Specialist to handle inbound tickets via email and "
            "chat. Requirements: excellent written communication, patience, familiarity "
            "with helpdesk tools (Zendesk/Intercom), and a knack for de-escalating issues."
        ),
        14,
    ),
]


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
        person = Person(
            first_name=first, last_name=last, email=email, created_at=now, updated_at=now
        )
        db.add(person)
        db.flush()

    app_user = db.scalar(
        select(ApplicationUser).where(
            ApplicationUser.identity_provider == "local",
            ApplicationUser.person_id == person.person_id,
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
        eng_designation = _get_or_create_designation(db, eng_dept, "Software Engineer")

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
            email="employee@example.com",
            first="Sam",
            last="Employee",
            password="employee123",
            role="EMPLOYEE",
            department=eng_dept,
            designation=eng_designation,
            employee_code="EMP-STAFF-001",
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

        # sample vacancies, one per title (idempotent: skip titles that already exist)
        created = 0
        if manager is not None:
            for title, dept_name, employment_type, description, days_open in SAMPLE_VACANCIES:
                if db.scalar(select(Vacancy).where(Vacancy.title == title)) is not None:
                    continue
                dept = _get_or_create_department(db, dept_name)
                db.add(
                    Vacancy(
                        title=title,
                        department_id=dept.department_id,
                        description=description,
                        employment_type=employment_type,
                        opening_date=clock.today(),
                        closing_date=clock.today() + timedelta(days=days_open),
                        created_by_employee_id=manager.employee_id,
                        approval_status="APPROVED",
                        status="OPEN",
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1

        db.commit()
        print(
            f"Seed complete: demo manager + employee + candidate ready, "
            f"{created} new vacancy(ies) added."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
