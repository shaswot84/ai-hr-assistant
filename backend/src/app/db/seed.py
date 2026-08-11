from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

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
from app.domain.leave import LeaveBalance, LeaveType
from app.domain.recruitment import Vacancy
from app.shared.clock import get_clock

# (name, description, default_days, requires_approval, is_paid, max_consecutive_days)
SAMPLE_LEAVE_TYPES = [
    ("Annual Leave", "Planned time off for rest and personal use.", Decimal(20), True, True, None),
    ("Sick Leave", "Time off to recover from illness or injury.", Decimal(10), True, True, 5),
    ("Casual Leave", "Short-notice leave for personal matters.", Decimal(7), True, True, 3),
    ("Unpaid Leave", "Leave beyond paid entitlements.", Decimal(0), True, False, None),
]

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
        "Frontend Engineer",
        "Engineering",
        "FULL_TIME",
        (
            "We're hiring a Frontend Engineer with strong experience in React, TypeScript, "
            "and modern state management. You'll own UI implementation, performance, and "
            "accessibility, working closely with design and backend teams. Experience with "
            "Next.js and component design systems is required."
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


def _seed_leave_types(db) -> list[LeaveType]:
    """Idempotently create the standard leave types, returning all active ones."""
    for name, description, default_days, requires_approval, is_paid, max_consecutive in (
        SAMPLE_LEAVE_TYPES
    ):
        if db.scalar(select(LeaveType).where(LeaveType.leave_name == name)) is not None:
            continue
        db.add(
            LeaveType(
                leave_name=name,
                description=description,
                default_days=default_days,
                requires_approval=requires_approval,
                is_paid=is_paid,
                max_consecutive_days=max_consecutive,
                status="ACTIVE",
            )
        )
    db.flush()
    return list(db.scalars(select(LeaveType).where(LeaveType.status == "ACTIVE")))


def _seed_leave_balances(db, employee: Employee, leave_types: list[LeaveType], year: int) -> None:
    """Idempotently give an employee a balance row per leave type for the given year."""
    now = get_clock().now()
    for leave_type in leave_types:
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.employee_id,
            LeaveBalance.leave_type_id == leave_type.leave_type_id,
            LeaveBalance.year == year,
        )
        if db.scalar(stmt) is not None:
            continue
        db.add(
            LeaveBalance(
                employee_id=employee.employee_id,
                leave_type_id=leave_type.leave_type_id,
                year=year,
                allocated_days=leave_type.default_days,
                used_days=Decimal(0),
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

        # ---- people module demo data: a small org tree ------------------
        # Two more employees (Engineering lead + Finance analyst) plus
        # reporting lines: Priya -> Sam -> Hiring Manager. Idempotent: the
        # user/employee rows are created once, the manager links are
        # re-applied every run.
        eng_lead_designation = _get_or_create_designation(db, eng_dept, "Engineering Lead")
        finance_dept = _get_or_create_department(db, "Finance")
        analyst_designation = _get_or_create_designation(db, finance_dept, "Financial Analyst")

        _provision_user(
            db,
            email="priya@example.com",
            first="Priya",
            last="Chen",
            password="priya123",
            role="EMPLOYEE",
            department=eng_dept,
            designation=eng_lead_designation,
            employee_code="EMP-ENG-001",
        )
        _provision_user(
            db,
            email="arjun@example.com",
            first="Arjun",
            last="Patel",
            password="arjun123",
            role="EMPLOYEE",
            department=finance_dept,
            designation=analyst_designation,
            employee_code="EMP-FIN-001",
        )

        def _employee_by_email(db, email):
            return db.scalar(
                select(Employee)
                .join(Person, Employee.person_id == Person.person_id)
                .where(Person.email == email)
            )

        sam = _employee_by_email(db, "employee@example.com")
        priya = _employee_by_email(db, "priya@example.com")
        arjun = _employee_by_email(db, "arjun@example.com")
        if sam is not None and manager is not None:
            sam.manager_employee_id = manager.employee_id
        if priya is not None and sam is not None:
            priya.manager_employee_id = sam.employee_id
        db.commit()

        # ---- leave management demo data: standard leave types + a starting
        # balance per employee for the current year (idempotent).
        leave_types = _seed_leave_types(db)
        this_year = clock.today().year
        for employee in (manager, sam, priya, arjun):
            if employee is not None:
                _seed_leave_balances(db, employee, leave_types, this_year)
        db.commit()

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
