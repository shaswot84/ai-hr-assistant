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
from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy
from app.evaluation.keyword_suggestion import TIER_WEIGHTS
from app.shared.clock import get_clock

# (name, description, default_days, requires_approval, is_paid, max_consecutive_days)
SAMPLE_LEAVE_TYPES = [
    ("Annual Leave", "Planned time off for rest and personal use.", Decimal(20), True, True, None),
    ("Sick Leave", "Time off to recover from illness or injury.", Decimal(10), True, True, 5),
    ("Casual Leave", "Short-notice leave for personal matters.", Decimal(7), True, True, 3),
    ("Unpaid Leave", "Leave beyond paid entitlements.", Decimal(0), True, False, None),
]

# A spread of roles/departments so the candidate portal and AI scoring demo
# have variety. `scoring_keywords` is a hardcoded example rubric per role
# (not LLM-generated — seeding must stay fast and work with no AI provider
# configured) mirroring what "Generate Weighted Keywords" would plausibly
# suggest from the description: critical = stated as a requirement,
# important = a strongly implied core skill, nice_to_have = mentioned but
# not central.
SAMPLE_VACANCIES = [
    {
        "title": "Senior Backend Engineer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Senior Backend Engineer to design and build scalable APIs. "
            "Requirements: Python, FastAPI, PostgreSQL, Docker, Kubernetes, AWS, and "
            "mentoring junior engineers."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "python", "tier": "critical"},
            {"keyword": "fastapi", "tier": "critical"},
            {"keyword": "postgresql", "tier": "critical"},
            {"keyword": "docker", "tier": "important"},
            {"keyword": "kubernetes", "tier": "important"},
            {"keyword": "aws", "tier": "important"},
            {"keyword": "mentoring", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Product Designer",
        "department": "Design",
        "employment_type": "FULL_TIME",
        "description": (
            "We're looking for a Product Designer with strong Figma, prototyping, and user "
            "research skills. Experience with design systems and cross-functional "
            "collaboration with engineering is a must."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "figma", "tier": "critical"},
            {"keyword": "prototyping", "tier": "critical"},
            {"keyword": "user research", "tier": "critical"},
            {"keyword": "design systems", "tier": "important"},
            {"keyword": "cross-functional collaboration", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Data Analyst",
        "department": "Data",
        "employment_type": "FULL_TIME",
        "description": (
            "Seeking a Data Analyst to turn raw data into decisions. Requirements: SQL, "
            "Python (pandas), dashboarding (Looker/Tableau/Metabase), A/B test analysis, "
            "and clear written communication with non-technical stakeholders."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "sql", "tier": "critical"},
            {"keyword": "python", "tier": "critical"},
            {"keyword": "tableau", "tier": "important"},
            {"keyword": "a/b testing", "tier": "important"},
            {"keyword": "stakeholder communication", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "HR Generalist",
        "department": "Human Resources",
        "employment_type": "FULL_TIME",
        "description": (
            "Join our People team as an HR Generalist covering recruitment coordination, "
            "onboarding, employee relations, and policy administration. Requirements: 2+ "
            "years HR experience, HRIS familiarity, and strong interpersonal skills."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "hr experience", "tier": "critical"},
            {"keyword": "hris", "tier": "important"},
            {"keyword": "employee relations", "tier": "important"},
            {"keyword": "interpersonal skills", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "DevOps Engineer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "Looking for a DevOps Engineer to own our cloud infrastructure. Requirements: "
            "Kubernetes, Terraform, AWS, CI/CD pipelines (GitHub Actions), Docker, "
            "observability (Prometheus/Grafana), and on-call incident response experience."
        ),
        "days_open": 30,
        "scoring_keywords": [
            {"keyword": "kubernetes", "tier": "critical"},
            {"keyword": "terraform", "tier": "critical"},
            {"keyword": "aws", "tier": "critical"},
            {"keyword": "docker", "tier": "important"},
            {"keyword": "continuous integration", "tier": "important"},
            {"keyword": "prometheus", "tier": "nice_to_have"},
            {"keyword": "on-call incident response", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Marketing Manager",
        "department": "Marketing",
        "employment_type": "FULL_TIME",
        "description": (
            "We need a Marketing Manager to own campaign strategy across paid, content, and "
            "lifecycle channels. Requirements: 4+ years B2B/B2C marketing, analytics tools "
            "(GA4/Mixpanel), budget management, and experience briefing design/content teams."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "b2b marketing", "tier": "critical"},
            {"keyword": "marketing analytics", "tier": "important"},
            {"keyword": "budget management", "tier": "important"},
            {"keyword": "content strategy", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Frontend Engineer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a Frontend Engineer with strong experience in React, TypeScript, "
            "and modern state management. You'll own UI implementation, performance, and "
            "accessibility, working closely with design and backend teams. Experience with "
            "Next.js and component design systems is required."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "react", "tier": "critical"},
            {"keyword": "typescript", "tier": "critical"},
            {"keyword": "next.js", "tier": "critical"},
            {"keyword": "state management", "tier": "important"},
            {"keyword": "accessibility", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Customer Support Specialist",
        "department": "Operations",
        "employment_type": "PART_TIME",
        "description": (
            "Part-time Customer Support Specialist to handle inbound tickets via email and "
            "chat. Requirements: excellent written communication, patience, familiarity "
            "with helpdesk tools (Zendesk/Intercom), and a knack for de-escalating issues."
        ),
        "days_open": 14,
        "scoring_keywords": [
            {"keyword": "written communication", "tier": "critical"},
            {"keyword": "zendesk", "tier": "important"},
            {"keyword": "de-escalation", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "QA Engineer",
        "department": "Engineering",
        "employment_type": "FULL_TIME",
        "description": (
            "We're hiring a QA Engineer to own quality across our core product. Requirements: "
            "manual testing experience, automated testing with Selenium, and test plan "
            "authoring. Familiarity with CI/CD pipelines and bug tracking in Jira is a plus."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "manual testing", "tier": "critical"},
            {"keyword": "selenium", "tier": "critical"},
            {"keyword": "test planning", "tier": "important"},
            {"keyword": "continuous integration", "tier": "important"},
            {"keyword": "jira", "tier": "nice_to_have"},
        ],
    },
    {
        "title": "Sales Development Representative",
        "department": "Sales",
        "employment_type": "FULL_TIME",
        "description": (
            "Sales Development Representative to build and qualify our outbound pipeline. "
            "Requirements: cold outreach experience, CRM proficiency (Salesforce), and strong "
            "lead qualification skills. Experience with LinkedIn Sales Navigator is a bonus."
        ),
        "days_open": 21,
        "scoring_keywords": [
            {"keyword": "cold outreach", "tier": "critical"},
            {"keyword": "salesforce", "tier": "critical"},
            {"keyword": "lead qualification", "tier": "important"},
            {"keyword": "communication skills", "tier": "important"},
            {"keyword": "linkedin sales navigator", "tier": "nice_to_have"},
        ],
    },
]

# 50 distinct synthetic applicant names, cycled with SAMPLE_VACANCIES (5 per
# vacancy across 10 vacancies) and QUALITY_TIER_CYCLE (one of each match
# quality per vacancy) to seed a realistic, evenly-spread mix of good and bad
# examples for the requirements-gate/ranking UI to demonstrate — entirely
# deterministic and offline (no live LLM calls, no real resume files), same
# reasoning as the hardcoded scoring_keywords above.
SAMPLE_APPLICANT_NAMES = [
    ("Olivia", "Martinez"), ("Liam", "Chen"), ("Emma", "Johansson"), ("Noah", "Okafor"),
    ("Ava", "Silva"), ("Ethan", "Kowalski"), ("Sophia", "Nguyen"), ("Mason", "Dubois"),
    ("Isabella", "Kim"), ("Lucas", "Andersson"), ("Mia", "Rossi"), ("James", "Osei"),
    ("Amelia", "Yamamoto"), ("Benjamin", "Costa"), ("Charlotte", "Ivanov"), ("Henry", "Abbas"),
    ("Harper", "Larsen"), ("Alexander", "Suzuki"), ("Evelyn", "Fischer"), ("Daniel", "Reyes"),
    ("Abigail", "Novak"), ("Matthew", "Haddad"), ("Emily", "Brennan"), ("Jackson", "Petrov"),
    ("Elizabeth", "Moreau"), ("Sebastian", "Adeyemi"), ("Sofia", "Lindqvist"), ("Jack", "Carvalho"),
    ("Avery", "Nakamura"), ("Owen", "Kaczmarek"), ("Ella", "Mensah"), ("Samuel", "Ortiz"),
    ("Scarlett", "Berg"), ("David", "Choudhury"), ("Grace", "Fontaine"), ("Joseph", "Tanaka"),
    ("Chloe", "Weber"), ("Carter", "Nkemelu"), ("Victoria", "Sorensen"), ("Wyatt", "Almeida"),
    ("Riley", "Volkov"), ("Luke", "Osman"), ("Zoey", "Bergstrom"), ("Gabriel", "Salazar"),
    ("Penelope", "Kimura"), ("Julian", "Adesanya"), ("Layla", "Marchetti"), ("Levi", "Halvorsen"),
    ("Nora", "Ibrahim"), ("Isaac", "Whitfield"),
]

# One of each per vacancy (5 applicants per vacancy, 10 vacancies = 50 total).
QUALITY_TIER_CYCLE = ["strong", "good", "moderate", "weak", "failing"]


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


def _synthetic_keyword_matches(scoring_keywords: list[dict], quality_tier: str) -> list[dict]:
    """Deterministically decide keyword presence for a synthetic applicant.

    Mirrors the shape the real scoring LLM returns (keyword/present/evidence)
    so the seeded evaluation renders identically to a live one. "weak" fails
    exactly its vacancy's first critical keyword — enough to trip the
    requirements gate while still leaving a plausible partial match; "failing"
    matches nothing.
    """
    criticals = [kw["keyword"] for kw in scoring_keywords if kw["tier"] == "critical"]
    importants = [kw["keyword"] for kw in scoring_keywords if kw["tier"] == "important"]
    first_critical = criticals[0] if criticals else None
    half_importants = set(importants[: (len(importants) + 1) // 2])

    matches = []
    for kw in scoring_keywords:
        keyword, tier = kw["keyword"], kw["tier"]
        if quality_tier == "strong":
            present = True
        elif quality_tier == "good":
            present = tier in ("critical", "important")
        elif quality_tier == "moderate":
            present = tier == "critical" or keyword in half_importants
        elif quality_tier == "weak":
            present = tier == "critical" and keyword != first_critical
        else:  # failing
            present = False
        evidence = (
            f"Resume clearly evidences {keyword}." if present else f"No mention of {keyword} in the resume."
        )
        matches.append({"keyword": keyword, "present": present, "evidence": evidence})
    return matches


def _synthetic_requirements(scoring_keywords: list[dict], matches: list[dict]) -> list[dict]:
    """Build a synthetic 'requirements' list from the vacancy's critical-tier keywords.

    Mirrors how the real system's hard-requirements gate lines up with
    critical keywords in this seed data's job descriptions (both are phrased
    as "Requirements: X, Y, Z").
    """
    present_by_keyword = {m["keyword"]: m["present"] for m in matches}
    requirements = []
    for kw in scoring_keywords:
        if kw["tier"] != "critical":
            continue
        met = present_by_keyword.get(kw["keyword"], False)
        requirements.append(
            {
                "requirement": kw["keyword"],
                "met": met,
                "evidence": "Verified in resume." if met else f"No mention of {kw['keyword']} in resume.",
            }
        )
    return requirements


def _synthetic_score(scoring_keywords: list[dict], matches: list[dict]) -> int:
    """Same weighted formula as the real evaluation.scoring._compute_keyword_score."""
    tier_by_keyword = {kw["keyword"]: kw["tier"] for kw in scoring_keywords}
    total_weight = sum(TIER_WEIGHTS[t] for t in tier_by_keyword.values())
    if total_weight == 0:
        return 0
    present = {m["keyword"] for m in matches if m["present"]}
    matched_weight = sum(TIER_WEIGHTS[tier_by_keyword[k]] for k in present)
    return round(100 * matched_weight / total_weight)


def _synthetic_recommendation(score: int, requirements_met: bool) -> str:
    if not requirements_met:
        return "Does Not Meet Requirements"
    if score >= 85:
        return "Strong Match"
    if score >= 60:
        return "Good Match"
    if score >= 35:
        return "Possible Match"
    return "Weak Match"


def _build_synthetic_evaluation(
    *, vacancy_title: str, candidate_name: str, scoring_keywords: list[dict], quality_tier: str
) -> tuple[dict, int, bool, str]:
    """Return (raw_payload, keyword_score, requirements_met, overview) for a synthetic evaluation."""
    matches = _synthetic_keyword_matches(scoring_keywords, quality_tier)
    requirements = _synthetic_requirements(scoring_keywords, matches)
    requirements_met = all(r["met"] for r in requirements) if requirements else True
    score = _synthetic_score(scoring_keywords, matches)
    recommendation = _synthetic_recommendation(score, requirements_met)

    matched = [m["keyword"] for m in matches if m["present"]]
    missing = [m["keyword"] for m in matches if not m["present"]]
    summary = (
        f"{candidate_name} {'meets' if requirements_met else 'does not meet'} the stated requirements "
        f"for {vacancy_title}, with a weighted keyword match of {score}%."
    )

    raw_payload = {
        "requirements": requirements,
        "requirementsMet": requirements_met,
        "recommendation": recommendation,
        "summary": summary,
        "keyFactors": [
            {
                "factor": "Skills Match",
                "note": f"Matches {len(matched)} of {len(scoring_keywords)} configured keywords for this role.",
            },
        ],
        "strengths": [f"Demonstrates {kw}" for kw in matched[:4]],
        "weaknesses": [f"No evidence of {kw}" for kw in missing[:4]],
        "matchedKeywords": matched,
        "missingKeywords": missing,
        "keywordMatches": matches,
        "candidateProfile": {
            "name": candidate_name,
            "email": "",
            "phone": "",
            "location": "",
            "headline": f"Applicant for {vacancy_title}",
        },
    }
    return raw_payload, score, requirements_met, summary


def _seed_sample_applications(db, clock) -> int:
    """Idempotently seed synthetic candidates + applications + evaluations across SAMPLE_VACANCIES.

    Fully deterministic and offline (no resume files, no live LLM calls) —
    same reasoning as the hardcoded scoring_keywords: seeding must stay fast
    and work without an AI provider configured. Re-running skips any
    (candidate, vacancy) pair that already has an application.
    """
    now = clock.now()
    created = 0
    for i, (first, last) in enumerate(SAMPLE_APPLICANT_NAMES):
        vacancy_def = SAMPLE_VACANCIES[i % len(SAMPLE_VACANCIES)]
        # NOT `i % len(QUALITY_TIER_CYCLE)`: with 10 vacancies and 5 tiers,
        # `i % 10` and `i % 5` are correlated (10 is a multiple of 5), so
        # that would give every applicant of a given vacancy the SAME tier
        # instead of one of each. `i // len(SAMPLE_VACANCIES)` is this
        # applicant's position within their vacancy's 5-applicant group
        # (0..4), which does vary independently of the vacancy index.
        quality_tier = QUALITY_TIER_CYCLE[i // len(SAMPLE_VACANCIES)]
        email = f"{first.lower()}.{last.lower()}@applicant-seed.test"

        _provision_user(db, email=email, first=first, last=last, password="applicant123", role="CANDIDATE")
        person = db.scalar(select(Person).where(Person.email == email))
        candidate = db.scalar(select(Candidate).where(Candidate.person_id == person.person_id))
        vacancy = db.scalar(select(Vacancy).where(Vacancy.title == vacancy_def["title"]))
        if candidate is None or vacancy is None:
            continue

        existing = db.scalar(
            select(Application).where(
                Application.candidate_id == candidate.candidate_id,
                Application.vacancy_id == vacancy.vacancy_id,
            )
        )
        if existing is not None:
            continue

        applied_at = now - timedelta(days=(i % 14), hours=(i * 3) % 24)
        application = Application(
            candidate_id=candidate.candidate_id,
            vacancy_id=vacancy.vacancy_id,
            cv_object_key="resumes/seed-placeholder.pdf",
            application_status="APPLIED",
            applied_at=applied_at,
            updated_at=applied_at,
        )
        db.add(application)
        db.flush()

        raw_payload, score, _requirements_met, overview = _build_synthetic_evaluation(
            vacancy_title=vacancy_def["title"],
            candidate_name=f"{first} {last}",
            scoring_keywords=vacancy_def["scoring_keywords"],
            quality_tier=quality_tier,
        )
        db.add(
            ApplicationEvaluation(
                application_id=application.application_id,
                overview=overview,
                raw_payload=raw_payload,
                keyword_score=score,
                failed=False,
                model="gpt-oss:120b-cloud",
                prompt_version="recruitment-screen-v1",
                latency_ms=1800,
                evaluated_at=applied_at + timedelta(minutes=2),
            )
        )
        created += 1
    return created


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

        # sample applications: 50 synthetic candidates spread across the
        # vacancies above, evenly cycling through match-quality tiers so
        # every vacancy has both good and bad examples (idempotent).
        applications_created = _seed_sample_applications(db, clock)
        db.commit()

        print(
            f"Seed complete: demo manager + employee + candidate ready, "
            f"{created} new vacancy(ies) and {applications_created} new application(s) added."
        )
    finally:
        db.close()


if __name__ == "__main__":
    seed()
