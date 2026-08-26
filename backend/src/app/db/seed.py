from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.db.session import async_session_factory, init_db
from app.domain.identity import (
    ApplicationUser,
    Candidate,
    Department,
    Designation,
    Employee,
    Person,
)
from app.domain.leave import LeaveBalance, LeaveRequest, LeaveType
from app.domain.recruitment import Vacancy
from app.shared.clock import get_clock

# ---------------------------------------------------------------------------
# Leave Types
# ---------------------------------------------------------------------------
SAMPLE_LEAVE_TYPES = [
    ("Annual Leave", "Planned time off for rest and personal use.", Decimal(20), True, True, None),
    ("Sick Leave", "Time off to recover from illness or injury.", Decimal(10), True, True, 5),
    ("Casual Leave", "Short-notice leave for personal matters.", Decimal(7), True, True, 3),
    ("Unpaid Leave", "Leave beyond paid entitlements.", Decimal(0), True, False, None),
]

# ---------------------------------------------------------------------------
# Departments and Designations (with Career Levels 1-5)
# ---------------------------------------------------------------------------
SAMPLE_DEPARTMENTS_AND_DESIGNATIONS: list[dict[str, Any]] = [
    {
        "name": "Engineering",
        "designations": [
            ("Chief Technology Officer", 1),
            ("Engineering Manager", 2),
            ("Principal Software Engineer", 2),
            ("Lead Backend Engineer", 3),
            ("Lead Frontend Engineer", 3),
            ("DevOps & Cloud Engineer", 3),
            ("Senior Software Engineer", 3),
            ("Software Engineer", 4),
            ("Junior Software Engineer", 5),
        ],
    },
    {
        "name": "Quality Assurance",
        "designations": [
            ("QA Lead", 2),
            ("Senior QA Automation Engineer", 3),
            ("QA Engineer", 4),
            ("Junior QA Engineer", 5),
        ],
    },
    {
        "name": "Product & Design",
        "designations": [
            ("Head of Product", 1),
            ("Senior Product Manager", 2),
            ("Lead UI/UX Designer", 3),
            ("Product Designer", 4),
            ("Associate UI/UX Designer", 5),
        ],
    },
    {
        "name": "Data & AI",
        "designations": [
            ("Lead Data Scientist", 2),
            ("Senior AI/ML Engineer", 3),
            ("Data Analyst", 4),
            ("Data Engineer", 4),
        ],
    },
    {
        "name": "Human Resources",
        "designations": [
            ("Head of People & Culture", 1),
            ("HR Manager", 2),
            ("Talent Acquisition Specialist", 3),
            ("HR Operations Officer", 4),
        ],
    },
    {
        "name": "Finance & Accounting",
        "designations": [
            ("Chief Financial Officer", 1),
            ("Finance Manager", 2),
            ("Senior Accountant", 3),
            ("Financial Analyst", 4),
            ("Accounts Officer", 5),
        ],
    },
    {
        "name": "Marketing & Growth",
        "designations": [
            ("Head of Marketing", 1),
            ("Brand & Growth Manager", 2),
            ("Digital Marketing Specialist", 3),
            ("Content & Social Media Strategist", 4),
        ],
    },
    {
        "name": "Sales & Business Development",
        "designations": [
            ("Head of Business Development", 1),
            ("Enterprise Sales Manager", 2),
            ("Business Development Executive", 3),
            ("Client Relationship Officer", 4),
        ],
    },
    {
        "name": "Operations & Administration",
        "designations": [
            ("Operations Manager", 2),
            ("Administration & Facilities Lead", 3),
            ("Office Operations Executive", 4),
        ],
    },
    {
        "name": "Customer Success & Support",
        "designations": [
            ("Customer Success Lead", 2),
            ("Senior Support Specialist", 3),
            ("Customer Support Associate", 4),
        ],
    },
]

# ---------------------------------------------------------------------------
# Demo Accounts + Realistic Nepali Roster
# ---------------------------------------------------------------------------
DEMO_EMPLOYEES: list[dict[str, Any]] = [
    {
        "email": "manager@example.com",
        "first": "Hiring",
        "last": "Manager",
        "password": "manager123",
        "role": "HR_ADMIN",
        "department": "Human Resources",
        "designation": "HR Manager",
        "employee_code": "EMP-MGR-001",
        "phone": "+977-9841000001",
        "manager_code": "EMP-EXEC-003",
        "days_ago": 1095,  # 3 years
    },
    {
        "email": "employee@example.com",
        "first": "Sam",
        "last": "Employee",
        "password": "employee123",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Software Engineer",
        "employee_code": "EMP-STAFF-001",
        "phone": "+977-9841000002",
        "manager_code": "EMP-ENG-002",
        "days_ago": 730,  # 2 years
    },
]

SAMPLE_NEPALI_EMPLOYEES: list[dict[str, Any]] = [
    # ---- Executive Leadership -------------------------------------------
    {
        "email": "aarav.shrestha@example.com",
        "first": "Aarav",
        "last": "Shrestha",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Engineering",
        "designation": "Chief Technology Officer",
        "employee_code": "EMP-EXEC-001",
        "phone": "+977-9851012345",
        "manager_code": None,
        "days_ago": 1825,  # 5 years
    },
    {
        "email": "binod.adhikari@example.com",
        "first": "Binod",
        "last": "Adhikari",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Finance & Accounting",
        "designation": "Chief Financial Officer",
        "employee_code": "EMP-EXEC-002",
        "phone": "+977-9851023456",
        "manager_code": None,
        "days_ago": 1800,
    },
    {
        "email": "dikshya.sharma@example.com",
        "first": "Dikshya",
        "last": "Sharma",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Human Resources",
        "designation": "Head of People & Culture",
        "employee_code": "EMP-EXEC-003",
        "phone": "+977-9851034567",
        "manager_code": None,
        "days_ago": 1600,
    },
    {
        "email": "pradeep.pokharel@example.com",
        "first": "Pradeep",
        "last": "Pokharel",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Product & Design",
        "designation": "Head of Product",
        "employee_code": "EMP-EXEC-004",
        "phone": "+977-9851045678",
        "manager_code": None,
        "days_ago": 1500,
    },
    {
        "email": "roshani.tamang@example.com",
        "first": "Roshani",
        "last": "Tamang",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Marketing & Growth",
        "designation": "Head of Marketing",
        "employee_code": "EMP-EXEC-005",
        "phone": "+977-9851056789",
        "manager_code": None,
        "days_ago": 1400,
    },
    {
        "email": "suman.thapa@example.com",
        "first": "Suman",
        "last": "Thapa",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Sales & Business Development",
        "designation": "Head of Business Development",
        "employee_code": "EMP-EXEC-006",
        "phone": "+977-9851067890",
        "manager_code": None,
        "days_ago": 1450,
    },
    # ---- Human Resources Team -------------------------------------------
    {
        "email": "anjali.gurung@example.com",
        "first": "Anjali",
        "last": "Gurung",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Human Resources",
        "designation": "Talent Acquisition Specialist",
        "employee_code": "EMP-HR-002",
        "phone": "+977-9841123456",
        "manager_code": "EMP-MGR-001",
        "days_ago": 600,
    },
    {
        "email": "bikash.karki@example.com",
        "first": "Bikash",
        "last": "Karki",
        "password": "12345678",
        "role": "HR_ADMIN",
        "department": "Human Resources",
        "designation": "HR Operations Officer",
        "employee_code": "EMP-HR-003",
        "phone": "+977-9841234567",
        "manager_code": "EMP-MGR-001",
        "days_ago": 450,
    },
    # ---- Engineering Team -----------------------------------------------
    {
        "email": "sandesh.gautam@example.com",
        "first": "Sandesh",
        "last": "Gautam",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Engineering Manager",
        "employee_code": "EMP-ENG-001",
        "phone": "+977-9841345678",
        "manager_code": "EMP-EXEC-001",
        "days_ago": 1200,
    },
    {
        "email": "pooja.maharjan@example.com",
        "first": "Pooja",
        "last": "Maharjan",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Lead Backend Engineer",
        "employee_code": "EMP-ENG-002",
        "phone": "+977-9841456789",
        "manager_code": "EMP-ENG-001",
        "days_ago": 900,
    },
    {
        "email": "manish.joshi@example.com",
        "first": "Manish",
        "last": "Joshi",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Lead Frontend Engineer",
        "employee_code": "EMP-ENG-003",
        "phone": "+977-9841567890",
        "manager_code": "EMP-ENG-001",
        "days_ago": 850,
    },
    {
        "email": "sneha.acharya@example.com",
        "first": "Sneha",
        "last": "Acharya",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "DevOps & Cloud Engineer",
        "employee_code": "EMP-ENG-004",
        "phone": "+977-9841678901",
        "manager_code": "EMP-EXEC-001",
        "days_ago": 700,
    },
    {
        "email": "rajesh.basnet@example.com",
        "first": "Rajesh",
        "last": "Basnet",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Senior Software Engineer",
        "employee_code": "EMP-ENG-005",
        "phone": "+977-9841789012",
        "manager_code": "EMP-ENG-002",
        "days_ago": 600,
    },
    {
        "email": "sunita.rai@example.com",
        "first": "Sunita",
        "last": "Rai",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Engineering",
        "designation": "Junior Software Engineer",
        "employee_code": "EMP-ENG-006",
        "phone": "+977-9841890123",
        "manager_code": "EMP-ENG-003",
        "days_ago": 250,
    },
    # ---- Quality Assurance Team -----------------------------------------
    {
        "email": "dipendra.regmi@example.com",
        "first": "Dipendra",
        "last": "Regmi",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Quality Assurance",
        "designation": "QA Lead",
        "employee_code": "EMP-QA-001",
        "phone": "+977-9841901234",
        "manager_code": "EMP-EXEC-001",
        "days_ago": 1000,
    },
    {
        "email": "kritika.bista@example.com",
        "first": "Kritika",
        "last": "Bista",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Quality Assurance",
        "designation": "Senior QA Automation Engineer",
        "employee_code": "EMP-QA-002",
        "phone": "+977-9841012340",
        "manager_code": "EMP-QA-001",
        "days_ago": 650,
    },
    {
        "email": "nabin.shakya@example.com",
        "first": "Nabin",
        "last": "Shakya",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Quality Assurance",
        "designation": "QA Engineer",
        "employee_code": "EMP-QA-003",
        "phone": "+977-9841012349",
        "manager_code": "EMP-QA-001",
        "days_ago": 300,
    },
    # ---- Product & Design Team ------------------------------------------
    {
        "email": "sandeep.sharma@example.com",
        "first": "Sandeep",
        "last": "Sharma",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Product & Design",
        "designation": "Senior Product Manager",
        "employee_code": "EMP-PRD-001",
        "phone": "+977-9860112233",
        "manager_code": "EMP-EXEC-004",
        "days_ago": 750,
    },
    {
        "email": "pratima.kc@example.com",
        "first": "Pratima",
        "last": "KC",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Product & Design",
        "designation": "Lead UI/UX Designer",
        "employee_code": "EMP-DES-001",
        "phone": "+977-9860223344",
        "manager_code": "EMP-EXEC-004",
        "days_ago": 800,
    },
    {
        "email": "rohan.dahal@example.com",
        "first": "Rohan",
        "last": "Dahal",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Product & Design",
        "designation": "Product Designer",
        "employee_code": "EMP-DES-002",
        "phone": "+977-9860334455",
        "manager_code": "EMP-DES-001",
        "days_ago": 400,
    },
    # ---- Data & AI Team -------------------------------------------------
    {
        "email": "ashmita.bhattarai@example.com",
        "first": "Ashmita",
        "last": "Bhattarai",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Data & AI",
        "designation": "Lead Data Scientist",
        "employee_code": "EMP-DAT-001",
        "phone": "+977-9860445566",
        "manager_code": "EMP-EXEC-001",
        "days_ago": 950,
    },
    {
        "email": "ujjwal.paudel@example.com",
        "first": "Ujjwal",
        "last": "Paudel",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Data & AI",
        "designation": "Senior AI/ML Engineer",
        "employee_code": "EMP-DAT-002",
        "phone": "+977-9860556677",
        "manager_code": "EMP-DAT-001",
        "days_ago": 600,
    },
    {
        "email": "sweta.bajracharya@example.com",
        "first": "Sweta",
        "last": "Bajracharya",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Data & AI",
        "designation": "Data Analyst",
        "employee_code": "EMP-DAT-003",
        "phone": "+977-9860667788",
        "manager_code": "EMP-DAT-001",
        "days_ago": 350,
    },
    # ---- Finance & Accounting Team --------------------------------------
    {
        "email": "nirajan.pandey@example.com",
        "first": "Nirajan",
        "last": "Pandey",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Finance & Accounting",
        "designation": "Finance Manager",
        "employee_code": "EMP-FIN-001",
        "phone": "+977-9801123450",
        "manager_code": "EMP-EXEC-002",
        "days_ago": 1100,
    },
    {
        "email": "sujan.neupane@example.com",
        "first": "Sujan",
        "last": "Neupane",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Finance & Accounting",
        "designation": "Senior Accountant",
        "employee_code": "EMP-FIN-002",
        "phone": "+977-9801234561",
        "manager_code": "EMP-FIN-001",
        "days_ago": 700,
    },
    {
        "email": "shreya.dahal@example.com",
        "first": "Shreya",
        "last": "Dahal",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Finance & Accounting",
        "designation": "Financial Analyst",
        "employee_code": "EMP-FIN-003",
        "phone": "+977-9801345672",
        "manager_code": "EMP-FIN-001",
        "days_ago": 400,
    },
    # ---- Marketing Team -------------------------------------------------
    {
        "email": "bibek.bista@example.com",
        "first": "Bibek",
        "last": "Bista",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Marketing & Growth",
        "designation": "Brand & Growth Manager",
        "employee_code": "EMP-MKT-001",
        "phone": "+977-9801456783",
        "manager_code": "EMP-EXEC-005",
        "days_ago": 800,
    },
    {
        "email": "sarita.acharya@example.com",
        "first": "Sarita",
        "last": "Acharya",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Marketing & Growth",
        "designation": "Digital Marketing Specialist",
        "employee_code": "EMP-MKT-002",
        "phone": "+977-9801567894",
        "manager_code": "EMP-MKT-001",
        "days_ago": 350,
    },
    # ---- Sales & Business Development Team ------------------------------
    {
        "email": "kushal.magar@example.com",
        "first": "Kushal",
        "last": "Magar",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Sales & Business Development",
        "designation": "Enterprise Sales Manager",
        "employee_code": "EMP-SLS-001",
        "phone": "+977-9801678905",
        "manager_code": "EMP-EXEC-006",
        "days_ago": 900,
    },
    {
        "email": "bandana.tiwari@example.com",
        "first": "Bandana",
        "last": "Tiwari",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Sales & Business Development",
        "designation": "Business Development Executive",
        "employee_code": "EMP-SLS-002",
        "phone": "+977-9801789016",
        "manager_code": "EMP-SLS-001",
        "days_ago": 400,
    },
    # ---- Operations & Customer Support Team -----------------------------
    {
        "email": "deepak.thapa@example.com",
        "first": "Deepak",
        "last": "Thapa",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Operations & Administration",
        "designation": "Operations Manager",
        "employee_code": "EMP-OPS-001",
        "phone": "+977-9801890127",
        "manager_code": "EMP-EXEC-003",
        "days_ago": 850,
    },
    {
        "email": "reema.maharjan@example.com",
        "first": "Reema",
        "last": "Maharjan",
        "password": "12345678",
        "role": "EMPLOYEE",
        "department": "Customer Success & Support",
        "designation": "Customer Success Lead",
        "employee_code": "EMP-CS-001",
        "phone": "+977-9801901238",
        "manager_code": "EMP-EXEC-006",
        "days_ago": 600,
    },
]

# ---------------------------------------------------------------------------
# Vacancies
# ---------------------------------------------------------------------------
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
        "department": "Marketing & Growth",
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
        "department": "Data & AI",
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
        "department": "Sales & Business Development",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Director of Sales to build and execute our go-to-market strategy. "
            "Requirements: 10+ years in enterprise B2B software sales, a track record of hiring "
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
    {
        "title": "HR Generalist",
        "department": "Human Resources",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring an HR Generalist to handle onboarding, benefits administration, "
            "and employee relations. Requirements: 2+ years in an HR role, working "
            "knowledge of employment law compliance, and strong interpersonal skills. "
            "Experience administering leave policies is a plus."
        ),
        "days_open": 14,
        "scoring_keywords": [
            {"keyword": "hr operations", "tier": "critical"},
            {"keyword": "employee relations", "tier": "critical"},
            {"keyword": "onboarding", "tier": "important"},
            {"keyword": "benefits administration", "tier": "important"},
            {"keyword": "employment law", "tier": "important"},
            {"keyword": "hris", "tier": "nice_to_have"},
        ],
    },
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
async def _get_or_create_department(db: AsyncSession, name: str) -> Department:
    """Return the department matching `name`, creating it if it does not yet exist."""
    dept = await db.scalar(select(Department).where(Department.name == name))
    if dept is None:
        dept = Department(name=name)
        db.add(dept)
        await db.flush()
    return dept


async def _get_or_create_designation(
    db: AsyncSession, department: Department, title: str, level: int | None = None
) -> Designation:
    """Return the designation matching (department, title), creating or updating it if needed."""
    stmt = select(Designation).where(
        Designation.department_id == department.department_id, Designation.title == title
    )
    designation = await db.scalar(stmt)
    if designation is None:
        designation = Designation(department_id=department.department_id, title=title, level=level)
        db.add(designation)
        await db.flush()
    elif level is not None and designation.level != level:
        designation.level = level
        await db.flush()
    return designation


async def _provision_user(
    db: AsyncSession,
    *,
    email: str,
    first: str,
    last: str,
    password: str,
    role: str,
    phone: str | None = None,
    department: Department | None = None,
    designation: Designation | None = None,
    employee_code: str | None = None,
    joining_date: date | None = None,
) -> Employee | None:
    """Idempotently create or update Person + ApplicationUser (+ Employee/Candidate)."""
    clock = get_clock()
    now = clock.now()

    person = await db.scalar(select(Person).where(Person.email == email))
    if person is None:
        person = Person(
            first_name=first,
            last_name=last,
            email=email,
            phone=phone,
            created_at=now,
            updated_at=now,
        )
        db.add(person)
        await db.flush()
    else:
        # Update existing person attributes
        person.first_name = first
        person.last_name = last
        if phone:
            person.phone = phone
        person.updated_at = now
        await db.flush()

    app_user = await db.scalar(
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
        await db.flush()
    else:
        app_user.coarse_role = role
        app_user.password_hash = hash_password(password)
        app_user.updated_at = now
        await db.flush()

    if role == "CANDIDATE":
        if (await db.scalar(select(Candidate).where(Candidate.person_id == person.person_id))) is None:
            db.add(
                Candidate(
                    person_id=person.person_id,
                    registration_date=clock.today(),
                    created_at=now,
                    updated_at=now,
                )
            )
        return None

    if role in ("HR_ADMIN", "EMPLOYEE"):
        if department is None or designation is None:
            raise ValueError("department and designation are required to seed an employee.")
        emp = await db.scalar(select(Employee).where(Employee.person_id == person.person_id))
        if emp is None:
            emp = Employee(
                person_id=person.person_id,
                employee_code=employee_code or f"EMP-{uuid.uuid4().hex[:8].upper()}",
                department_id=department.department_id,
                designation_id=designation.designation_id,
                joining_date=joining_date or clock.today(),
                created_at=now,
                updated_at=now,
            )
            db.add(emp)
            await db.flush()
        else:
            emp.department_id = department.department_id
            emp.designation_id = designation.designation_id
            if employee_code:
                emp.employee_code = employee_code
            if joining_date:
                emp.joining_date = joining_date
            emp.updated_at = now
            await db.flush()
        return emp

    return None


async def _seed_leave_types(db: AsyncSession) -> list[LeaveType]:
    """Idempotently create the standard leave types, returning all active ones."""
    for name, description, default_days, requires_approval, is_paid, max_consecutive in (
        SAMPLE_LEAVE_TYPES
    ):
        if (await db.scalar(select(LeaveType).where(LeaveType.leave_name == name))) is not None:
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
    await db.flush()
    scalars = await db.scalars(select(LeaveType).where(LeaveType.status == "ACTIVE"))
    return list(scalars)


async def _seed_leave_balances(
    db: AsyncSession, employee: Employee, leave_types: list[LeaveType], year: int
) -> None:
    """Idempotently give an employee a balance row per leave type for the given year."""
    now = get_clock().now()
    for leave_type in leave_types:
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee.employee_id,
            LeaveBalance.leave_type_id == leave_type.leave_type_id,
            LeaveBalance.year == year,
        )
        if (await db.scalar(stmt)) is not None:
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


async def _clean_stale_data(db: AsyncSession, allowed_emails: set[str]) -> None:
    """Remove legacy/stale persons, application users, and employee profiles not in allowed_emails."""
    stale_persons = (
        await db.scalars(select(Person).where(Person.email.not_in(allowed_emails)))
    ).all()
    if not stale_persons:
        return

    stale_person_ids = [p.person_id for p in stale_persons]
    stale_emps = (
        await db.scalars(select(Employee).where(Employee.person_id.in_(stale_person_ids)))
    ).all()
    stale_emp_ids = [e.employee_id for e in stale_emps]

    if stale_emp_ids:
        # Clear manager references to stale employees
        other_emps = (
            await db.scalars(
                select(Employee).where(Employee.manager_employee_id.in_(stale_emp_ids))
            )
        ).all()
        for oe in other_emps:
            oe.manager_employee_id = None
        await db.flush()

        # Unlink candidate hires if any
        candidates = (
            await db.scalars(
                select(Candidate).where(Candidate.hired_employee_id.in_(stale_emp_ids))
            )
        ).all()
        for c in candidates:
            c.hired_employee_id = None
        await db.flush()

        # Delete leave balances and leave requests of stale employees
        await db.execute(delete(LeaveBalance).where(LeaveBalance.employee_id.in_(stale_emp_ids)))
        await db.execute(delete(LeaveRequest).where(LeaveRequest.employee_id.in_(stale_emp_ids)))
        await db.execute(delete(Employee).where(Employee.person_id.in_(stale_person_ids)))

    # Delete candidates, application_users, persons
    await db.execute(delete(Candidate).where(Candidate.person_id.in_(stale_person_ids)))
    await db.execute(delete(ApplicationUser).where(ApplicationUser.person_id.in_(stale_person_ids)))
    await db.execute(delete(Person).where(Person.person_id.in_(stale_person_ids)))
    await db.commit()


# ---------------------------------------------------------------------------
# Main Seed Entrypoint
# ---------------------------------------------------------------------------
async def seed() -> None:
    """Seed the database with realistic Nepali org hierarchy, employees, and demo accounts."""
    await init_db()
    async with async_session_factory() as db:
        clock = get_clock()
        now = clock.now()
        today = clock.today()

        # 1. Allowed emails set for cleanup
        all_emp_defs = DEMO_EMPLOYEES + SAMPLE_NEPALI_EMPLOYEES
        allowed_emails = {d["email"] for d in all_emp_defs} | {"candidate@example.com"}

        # 2. Clean stale/legacy records
        await _clean_stale_data(db, allowed_emails)

        # 3. Seed all 10 Departments & 32 Designations
        dept_map: dict[str, Department] = {}
        desig_map: dict[tuple[str, str], Designation] = {}

        for dept_def in SAMPLE_DEPARTMENTS_AND_DESIGNATIONS:
            dept_name = dept_def["name"]
            dept = await _get_or_create_department(db, dept_name)
            dept_map[dept_name] = dept
            for title, level in dept_def["designations"]:
                desig = await _get_or_create_designation(db, dept, title, level)
                desig_map[(dept_name, title)] = desig
        await db.commit()

        # 4. Clean up / migrate legacy departments & unused designations
        legacy_dept_map = {
            "Finance": "Finance & Accounting",
            "Marketing": "Marketing & Growth",
            "Data": "Data & AI",
            "Sales": "Sales & Business Development",
        }
        for old_name, new_name in legacy_dept_map.items():
            old_dept = await db.scalar(select(Department).where(Department.name == old_name))
            if old_dept and new_name in dept_map:
                new_dept = dept_map[new_name]
                # Re-assign vacancies
                vacancies = (
                    await db.scalars(select(Vacancy).where(Vacancy.department_id == old_dept.department_id))
                ).all()
                for v in vacancies:
                    v.department_id = new_dept.department_id
                # Re-assign employees
                emps = (
                    await db.scalars(select(Employee).where(Employee.department_id == old_dept.department_id))
                ).all()
                for e in emps:
                    e.department_id = new_dept.department_id
                await db.flush()
                # Delete old designations for this old department
                await db.execute(delete(Designation).where(Designation.department_id == old_dept.department_id))
                # Delete old department
                await db.execute(delete(Department).where(Department.department_id == old_dept.department_id))
                await db.commit()

        # 5. Clean up any unused legacy designations without level
        emps_all = (await db.scalars(select(Employee))).all()
        used_desig_ids = {e.designation_id for e in emps_all}
        all_desigs = (await db.scalars(select(Designation))).all()
        for d in all_desigs:
            if d.level is None and d.designation_id not in used_desig_ids:
                await db.delete(d)
        await db.commit()

        # 6. Provision candidate demo account
        await _provision_user(
            db,
            email="candidate@example.com",
            first="Alex",
            last="Applicant",
            password="candidate123",
            role="CANDIDATE",
            phone="+977-9841000003",
        )

        # 7. Provision all employees (demo + Nepali staff)
        emp_by_code: dict[str, Employee] = {}
        for emp_def in all_emp_defs:
            dept = dept_map[emp_def["department"]]
            desig = desig_map[(emp_def["department"], emp_def["designation"])]
            joining_date = today - timedelta(days=emp_def.get("days_ago", 365))
            emp = await _provision_user(
                db,
                email=emp_def["email"],
                first=emp_def["first"],
                last=emp_def["last"],
                password=emp_def["password"],
                role=emp_def["role"],
                phone=emp_def.get("phone"),
                department=dept,
                designation=desig,
                employee_code=emp_def["employee_code"],
                joining_date=joining_date,
            )
            if emp:
                emp_by_code[emp_def["employee_code"]] = emp

        await db.commit()

        # 8. Wire up manager reporting hierarchy
        for emp_def in all_emp_defs:
            emp = emp_by_code.get(emp_def["employee_code"])
            mgr_code = emp_def.get("manager_code")
            if emp is not None:
                if mgr_code and mgr_code in emp_by_code:
                    emp.manager_employee_id = emp_by_code[mgr_code].employee_id
                else:
                    emp.manager_employee_id = None
        await db.commit()

        # 9. Seed Leave Types & Leave Balances
        leave_types = await _seed_leave_types(db)
        this_year = today.year
        for emp in emp_by_code.values():
            await _seed_leave_balances(db, emp, leave_types, this_year)
        await db.commit()

        # 10. Seed Sample Vacancies
        manager_emp = emp_by_code.get("EMP-MGR-001")
        vac_created = 0
        if manager_emp is not None:
            for vac in SAMPLE_VACANCIES:
                if (await db.scalar(select(Vacancy).where(Vacancy.title == vac["title"]))) is not None:
                    continue
                dept = dept_map.get(vac["department"]) or await _get_or_create_department(db, vac["department"])
                db.add(
                    Vacancy(
                        title=vac["title"],
                        department_id=dept.department_id,
                        description=vac["description"],
                        employment_type=vac["employment_type"],
                        opening_date=today,
                        closing_date=today + timedelta(days=vac["days_open"]),
                        created_by_employee_id=manager_emp.employee_id,
                        approval_status="APPROVED",
                        status="OPEN",
                        scoring_keywords=vac["scoring_keywords"],
                        created_at=now,
                        updated_at=now,
                    )
                )
                vac_created += 1
            await db.commit()

        print(
            f"✅ Seed complete: {len(dept_map)} departments, "
            f"{len(desig_map)} designations, {len(emp_by_code)} employees seeded with "
            f"realistic Nepali data & demo accounts, {vac_created} new vacancy(ies) added."
        )


if __name__ == "__main__":
    asyncio.run(seed())
