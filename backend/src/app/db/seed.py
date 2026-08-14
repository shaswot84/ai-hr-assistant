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

# A deliberately small, varied spread of departments and seniority levels
# (junior IC, senior IC, mid-level manager, junior/mid IC, senior exec) —
# not meant to be exhaustive, just enough for the requirements-gate/ranking
# UI to have believable, differently-shaped roles to demo against.
# `scoring_keywords` is a hardcoded example rubric per role (not
# LLM-generated — seeding must stay fast and work with no AI provider
# configured) mirroring what "Generate Weighted Keywords" would plausibly
# suggest from the description: critical = stated as a requirement,
# important = a strongly implied core skill, nice_to_have = mentioned but
# not central.
SAMPLE_VACANCIES = [
    {
        "title": "Junior Frontend Developer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Junior Frontend Developer to help build our customer-facing "
            "web app. Requirements: solid HTML, CSS, and JavaScript fundamentals, some "
            "hands-on experience with React, and familiarity with Git. This is an "
            "entry-level role — you'll be paired with senior engineers for mentorship "
            "as you grow."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "html", "tier": "critical"},
            {"keyword": "css", "tier": "critical"},
            {"keyword": "javascript", "tier": "critical"},
            {"keyword": "react", "tier": "important"},
            {"keyword": "git", "tier": "important"},
            {"keyword": "responsive design", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Senior Backend Engineer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Senior Backend Engineer to lead the design of our core "
            "services and mentor engineers on the team. Requirements: 7+ years of "
            "backend engineering experience, deep expertise in Python, hands-on system "
            "design for distributed systems, and a track record of mentoring or leading "
            "other engineers. AWS experience is a strong plus."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "python", "tier": "critical"},
            {"keyword": "distributed systems", "tier": "critical"},
            {"keyword": "system design", "tier": "critical"},
            {"keyword": "mentoring", "tier": "important"},
            {"keyword": "aws", "tier": "important"},
            {"keyword": "kubernetes", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Marketing Manager",
        "department": "Marketing",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Marketing Manager to own campaign strategy and lead a small "
            "team. Requirements: 5+ years of B2B marketing experience, a track record of "
            "managing marketing budgets, and experience leading or mentoring a team. "
            "Familiarity with GA4 and marketing analytics tools is expected."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "b2b marketing", "tier": "critical"},
            {"keyword": "budget management", "tier": "critical"},
            {"keyword": "team leadership", "tier": "important"},
            {"keyword": "marketing analytics", "tier": "important"},
            {"keyword": "content strategy", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Data Analyst",
        "department": "Data",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Data Analyst to help turn raw data into decisions across the "
            "company. Requirements: strong SQL skills and experience building dashboards "
            "or reports, plus the ability to communicate findings to non-technical "
            "stakeholders. Experience with Python (pandas) or Tableau is a plus."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "sql", "tier": "critical"},
            {"keyword": "data visualization", "tier": "critical"},
            {"keyword": "stakeholder communication", "tier": "important"},
            {"keyword": "python", "tier": "important"},
            {"keyword": "tableau", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Director of Sales",
        "department": "Sales",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Director of Sales to lead our sales organization through its "
            "next stage of growth. Requirements: 10+ years of sales experience with at "
            "least 5 years in a sales leadership role, a proven track record of building "
            "and leading high-performing sales teams, and experience driving significant "
            "revenue growth. Strong executive communication skills and enterprise sales "
            "experience are essential."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "sales leadership", "tier": "critical"},
            {"keyword": "revenue growth", "tier": "critical"},
            {"keyword": "team leadership", "tier": "critical"},
            {"keyword": "executive communication", "tier": "important"},
            {"keyword": "enterprise sales", "tier": "important"},
            {"keyword": "crm strategy", "tier": "nice_to_have"},
        ],
    },
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
            for vac in SAMPLE_VACANCIES:
                if db.scalar(select(Vacancy).where(Vacancy.title == vac["title"])) is not None:
                    continue
                dept = _get_or_create_department(db, vac["department"])
                db.add(
                    Vacancy(
                        title=vac["title"],
                        department_id=dept.department_id,
                        description=vac["description"],
                        employment_type=vac["employment_type"],
                        opening_date=clock.today(),
                        closing_date=clock.today() + timedelta(days=vac["days_open"]),
                        created_by_employee_id=manager.employee_id,
                        approval_status="APPROVED",
                        status="OPEN",
                        scoring_keywords=vac["scoring_keywords"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                created += 1

        db.commit()

        print(
            f"Seed complete: demo manager + employee + candidate ready, "
            f"{created} new vacancy(ies) added. Sample applications with real resumes are "
            f"seeded separately via `python -m app.db.seed_sample_applications` (requires a "
            f"configured AI provider and the worker running)."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
