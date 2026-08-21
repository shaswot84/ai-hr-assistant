"""Unit tests for the People (org directory) capability layer + HTTP routes.

Covers the M1 scope: departments, designations, employees (create/update/
list/deactivate with HR-provided credentials), the candidate → employee hire
handoff, and the employee self-service profile. Uses the same fixture style
as `test_recruitment.py` (SQLite-backed `db`, seeded role contexts).
"""

from __future__ import annotations

import uuid
from datetime import date

import pytest
from sqlalchemy import select

from app.capabilities.people import (
    ConflictError_,
    NotFoundError_,
    PeopleService,
    PermissionError_,
)
from app.capabilities.recruitment import RecruitmentService
from app.domain.audit import AuditLog
from app.domain.identity import ApplicationUser, Employee, Person
from app.domain.outbox import OutboxJob

# ---- shared helpers ------------------------------------------------------


async def _make_dept_and_designation(svc, manager_context, *, dept: str | None = None, title="Specialist"):
    """Create a department + designation via the service and return them."""
    dept = dept or f"People Ops {uuid.uuid4().hex[:6]}"
    department = await svc.create_department(manager_context, name=dept)
    designation = await svc.create_designation(
        manager_context, department_id=department.department_id, title=title
    )
    return department, designation


async def _create_employee(svc, manager_context, *, email=None, code=None, **overrides):
    """Create an employee via the service with sensible (unique) defaults."""
    email = email or f"new.employee.{uuid.uuid4().hex[:6]}@acme-hr-test.dev"
    code = code or f"EMP-{uuid.uuid4().hex[:6]}"
    department, designation = await _make_dept_and_designation(svc, manager_context)
    defaults = {
        "first_name": "New",
        "last_name": "Hire",
        "email": email,
        "phone": None,
        "employee_code": code,
        "department_id": department.department_id,
        "designation_id": designation.designation_id,
        "manager_employee_id": None,
        "joining_date": date(2026, 1, 15),
        "password": "temp-password-1",
    }
    defaults.update(overrides)
    return await svc.create_employee(manager_context, **defaults)


async def _shortlist_application(db, manager_context, candidate_context):
    """Create a vacancy, apply as the candidate, and shortlist — return the Application."""
    recruitment = RecruitmentService(db)
    vacancy = await recruitment.create_vacancy(
        manager_context,
        title="Senior Backend Engineer",
        department_name="Engineering",
        description="Build scalable APIs.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
        scoring_keywords=[{"keyword": "python", "tier": "critical"}],
    )
    application = await recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    await recruitment.decide_application(manager_context, application.application_id, approve=True)
    return application


async def _employee_of(svc, context) -> Employee:
    """Resolve a UserContext to its Employee row."""
    return await svc._identity.get_employee(context)


# ---- departments ---------------------------------------------------------


async def test_create_department_requires_hr_admin(db, candidate_context):
    svc = PeopleService(db)
    with pytest.raises(PermissionError_):
        await svc.create_department(candidate_context, name="Security")


async def test_create_department_duplicate_conflicts(db, manager_context):
    svc = PeopleService(db)
    await svc.create_department(manager_context, name="Operations")
    with pytest.raises(ConflictError_, match="already exists"):
        await svc.create_department(manager_context, name="Operations")


# ---- designations --------------------------------------------------------


async def test_create_designation_duplicate_conflicts(db, manager_context):
    svc = PeopleService(db)
    department, _ = await _make_dept_and_designation(svc, manager_context, title="Specialist")
    with pytest.raises(ConflictError_, match="already exists"):
        await svc.create_designation(manager_context, department_id=department.department_id, title="Specialist")


async def test_list_designations_filters_by_department(db, manager_context):
    svc = PeopleService(db)
    dept_a, _ = await _make_dept_and_designation(svc, manager_context, dept="Alpha", title="Role A")
    dept_b, _ = await _make_dept_and_designation(svc, manager_context, dept="Beta", title="Role B")
    desigs_a = await svc.list_designations(department_id=dept_a.department_id)
    titles = {d.title for d in desigs_a}
    assert titles == {"Role A"}
    all_desigs = await svc.list_designations()
    all_ids = {d.department_id for d in all_desigs}
    assert {dept_a.department_id, dept_b.department_id} <= all_ids


async def test_list_designations_unknown_department_raises(db, manager_context):
    svc = PeopleService(db)
    with pytest.raises(NotFoundError_):
        await svc.list_designations(department_id=uuid.UUID("00000000-0000-0000-0000-000000000000"))


# ---- employees: create ---------------------------------------------------


async def test_create_employee_requires_hr_admin(db, manager_context, candidate_context):
    svc = PeopleService(db)
    department, designation = await _make_dept_and_designation(svc, manager_context)
    with pytest.raises(PermissionError_):
        await svc.create_employee(
            candidate_context,
            first_name="X",
            last_name="Y",
            email="x@acme-hr-test.dev",
            phone=None,
            employee_code="EMP-X",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 1, 1),
            password="password-1",
        )


async def test_create_employee_provisions_person_user_and_employee(db, manager_context):
    svc = PeopleService(db)
    employee = await _create_employee(svc, manager_context, email="prov@acme-hr-test.dev", code="EMP-101")
    await db.refresh(employee)

    person = await db.get(Person, employee.person_id)
    app_user = await db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == person.person_id)
    )
    assert person.email == "prov@acme-hr-test.dev"
    assert app_user.coarse_role == "EMPLOYEE"
    assert app_user.status == "ACTIVE"
    assert employee.employment_status == "ACTIVE"
    employees = await svc.list_employees()
    assert any(e.employee_id == employee.employee_id for e in employees)


async def test_create_employee_duplicate_email_conflicts(db, manager_context):
    svc = PeopleService(db)
    await _create_employee(svc, manager_context, email="dup@acme-hr-test.dev")
    with pytest.raises(ConflictError_, match="email already exists"):
        await _create_employee(svc, manager_context, email="dup@acme-hr-test.dev", code="EMP-200")


async def test_create_employee_duplicate_code_conflicts(db, manager_context):
    svc = PeopleService(db)
    await _create_employee(svc, manager_context, code="EMP-300")
    with pytest.raises(ConflictError_, match="code already exists"):
        await _create_employee(svc, manager_context, email="other@acme-hr-test.dev", code="EMP-300")


async def test_create_employee_unknown_department_raises(db, manager_context):
    svc = PeopleService(db)
    _, designation = await _make_dept_and_designation(svc, manager_context)
    with pytest.raises(NotFoundError_, match="Department not found"):
        await _create_employee(
            svc,
            manager_context,
            department_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            designation_id=designation.designation_id,
        )


async def test_create_employee_manager_must_be_active(db, manager_context, employee_context):
    svc = PeopleService(db)
    manager = await _employee_of(svc, manager_context)
    await svc.deactivate_employee(manager_context, manager.employee_id)
    with pytest.raises(ConflictError_, match="active employee"):
        await _create_employee(svc, manager_context, manager_employee_id=manager.employee_id)


async def test_create_employee_stores_email_lowercase_for_login(db, manager_context):
    svc = PeopleService(db)
    employee = await _create_employee(svc, manager_context, email="Mixed.Case@Acme-Hr-Test.Dev")
    person = await db.get(Person, employee.person_id)
    assert person.email == "mixed.case@acme-hr-test.dev"


# ---- employees: list / get / update --------------------------------------


async def test_list_employees_filters_by_search_and_status(db, manager_context):
    svc = PeopleService(db)
    active = await _create_employee(svc, manager_context, first_name="Zara", last_name="Active", code="EMP-400")
    await _create_employee(svc, manager_context, first_name="Bob", last_name="Inactive", code="EMP-401")
    await svc.deactivate_employee(manager_context, active.employee_id)

    zaras = await svc.list_employees(search="zara")
    names = {f"{e.person.first_name} {e.person.last_name}" for e in zaras}
    assert names == {"Zara Active"}
    inactives = await svc.list_employees(employment_status="INACTIVE")
    inactive_codes = {e.employee_code for e in inactives}
    assert inactive_codes == {"EMP-400"}
    actives = await svc.list_employees(employment_status="ACTIVE")
    active_codes = {e.employee_code for e in actives}
    assert "EMP-400" not in active_codes
    assert "EMP-401" in active_codes


async def test_employee_can_view_own_profile_only(db, manager_context, employee_context):
    svc = PeopleService(db)
    own = await _employee_of(svc, employee_context)
    other = await _employee_of(svc, manager_context)

    own_profile = await svc.get_employee(employee_context, own.employee_id)
    assert own_profile.employee_id == own.employee_id
    with pytest.raises(PermissionError_):
        await svc.get_employee(employee_context, other.employee_id)
    mgr_view_own = await svc.get_employee(manager_context, own.employee_id)
    assert mgr_view_own.employee_id == own.employee_id
    mgr_view_other = await svc.get_employee(manager_context, other.employee_id)
    assert mgr_view_other.employee_id == other.employee_id


async def test_update_employee_patch_and_audit(db, manager_context):
    svc = PeopleService(db)
    employee = await _create_employee(svc, manager_context)
    manager = await _employee_of(svc, manager_context)

    await svc.update_employee(
        manager_context, employee.employee_id, first_name="Renamed", manager_employee_id=manager.employee_id
    )
    updated = await svc.get_employee(manager_context, employee.employee_id)
    assert updated.person.first_name == "Renamed"
    assert updated.manager_employee_id == manager.employee_id


    entry = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "EMPLOYEE_UPDATED")
    )).first()
    assert entry is not None
    assert entry.new_state["manager_employee_id"] == str(manager.employee_id)


# ---- employees: deactivate -----------------------------------------------


async def test_deactivate_employee_revokes_login(db, manager_context, employee_context):
    svc = PeopleService(db)
    employee = await _employee_of(svc, employee_context)

    deactivated = await svc.deactivate_employee(manager_context, employee.employee_id)
    assert deactivated.employment_status == "INACTIVE"

    app_user = await db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == employee.person_id)
    )
    assert app_user.status == "INACTIVE"
    entry = (await db.scalars(
        select(AuditLog).where(AuditLog.action == "EMPLOYEE_DEACTIVATED")
    )).first()
    assert entry is not None


async def test_deactivate_employee_blocked_with_active_reports(db, manager_context, employee_context):
    svc = PeopleService(db)
    manager = await _employee_of(svc, manager_context)
    report = await _employee_of(svc, employee_context)
    await svc.update_employee(manager_context, report.employee_id, manager_employee_id=manager.employee_id)
    with pytest.raises(ConflictError_, match="manages active reports"):
        await svc.deactivate_employee(manager_context, manager.employee_id)


# ---- hire handoff --------------------------------------------------------


async def test_hire_candidate_requires_hr_admin(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = await _shortlist_application(db, manager_context, candidate_context)
    department, designation = await _make_dept_and_designation(svc, manager_context)
    with pytest.raises(PermissionError_):
        await svc.hire_candidate(
            candidate_context,
            application.application_id,
            employee_code="EMP-500",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


async def test_hire_candidate_creates_employee_and_links_candidate(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = await _shortlist_application(db, manager_context, candidate_context)
    department, designation = await _make_dept_and_designation(svc, manager_context)

    employee = await svc.hire_candidate(
        manager_context,
        application.application_id,
        employee_code="EMP-500",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )
    await db.refresh(employee)

    candidate = await svc._identity.get_candidate_for_application(application)
    assert employee.person_id == candidate.person_id
    assert employee.employment_status == "ACTIVE"
    await db.refresh(candidate)
    assert candidate.hired_employee_id == employee.employee_id
    assert candidate.candidate_status == "HIRED"
    assert candidate.hired_at is not None
    app_user = await db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == candidate.person_id)
    )
    assert app_user.coarse_role == "EMPLOYEE"
    entry = (await db.scalars(select(AuditLog).where(AuditLog.action == "CANDIDATE_HIRED"))).first()
    assert entry is not None
    assert entry.new_state["employee_id"] == str(employee.employee_id)


async def test_hire_candidate_requires_shortlisted(db, manager_context, candidate_context):
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    vacancy = await recruitment.create_vacancy(
        manager_context,
        title="Junior Engineer",
        department_name="Engineering",
        description="Entry level.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
        scoring_keywords=[{"keyword": "python", "tier": "critical"}],
    )
    application = await recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/b.pdf"
    )
    department, designation = await _make_dept_and_designation(svc, manager_context)
    with pytest.raises(ConflictError_, match="SHORTLISTED"):
        await svc.hire_candidate(
            manager_context,
            application.application_id,
            employee_code="EMP-501",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


async def test_hire_candidate_already_hired_conflicts(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = await _shortlist_application(db, manager_context, candidate_context)
    department, designation = await _make_dept_and_designation(svc, manager_context)
    await svc.hire_candidate(
        manager_context,
        application.application_id,
        employee_code="EMP-502",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )
    with pytest.raises(ConflictError_, match="already been hired"):
        await svc.hire_candidate(
            manager_context,
            application.application_id,
            employee_code="EMP-503",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


async def test_hire_candidate_withdraws_other_open_applications(db, manager_context, candidate_context):
    """Hiring from one application withdraws the candidate's other open ones and emails them."""
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    v1 = await recruitment.create_vacancy(
        manager_context, title="Senior Backend Engineer", department_name="Engineering",
        description="Build APIs.", employment_type="full_time", opening_date=None, closing_date=None,
        scoring_keywords=[{"keyword": "python", "tier": "critical"}],
    )
    v2 = await recruitment.create_vacancy(
        manager_context, title="Data Analyst", department_name="Data",
        description="Analyze data.", employment_type="full_time", opening_date=None, closing_date=None,
        scoring_keywords=[{"keyword": "sql", "tier": "critical"}],
    )
    hired_app = await recruitment.apply(candidate_context, vacancy_id=v1.vacancy_id, cv_object_key="resumes/a.pdf")
    other_app = await recruitment.apply(candidate_context, vacancy_id=v2.vacancy_id, cv_object_key="resumes/b.pdf")
    await recruitment.decide_application(manager_context, hired_app.application_id, approve=True)
    await recruitment.decide_application(manager_context, other_app.application_id, approve=True)

    department, designation = await _make_dept_and_designation(svc, manager_context)
    await svc.hire_candidate(
        manager_context,
        hired_app.application_id,
        employee_code="EMP-600",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )

    await db.refresh(hired_app)
    await db.refresh(other_app)
    assert hired_app.application_status == "SHORTLISTED"
    assert other_app.application_status == "WITHDRAWN"
    assert other_app.withdrawn_at is not None

    jobs = (await db.scalars(
        select(OutboxJob).where(OutboxJob.job_type == "SEND_APPLICATION_WITHDRAWN")
    )).all()
    assert len(jobs) == 1
    assert jobs[0].payload["to_email"] == candidate_context.email
    assert jobs[0].payload["application_id"] == str(other_app.application_id)


async def test_application_detail_exposes_hired_flag(
    db, client, manager_context, candidate_context, manager_password
):
    """The manager API marks an application as hired once the candidate was converted."""
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    vacancy = await recruitment.create_vacancy(
        manager_context, title="Product Designer", department_name="Design",
        description="Design products.", employment_type="full_time",
        opening_date=None, closing_date=None,
        scoring_keywords=[{"keyword": "figma", "tier": "critical"}],
    )
    application = await recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    await recruitment.decide_application(manager_context, application.application_id, approve=True)
    department, designation = await _make_dept_and_designation(svc, manager_context)
    await svc.hire_candidate(
        manager_context,
        application.application_id,
        employee_code="EMP-700",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )

    headers = _login(client, manager_context.email, manager_password)
    res = client.get(f"/api/applications/{application.application_id}", headers=headers)
    assert res.status_code == 200
    assert res.json()["hired"] is True


# ---- HTTP layer ----------------------------------------------------------


def _login(client, email, password):
    """Log in and return the Authorization header for the given user."""
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


def test_http_employee_cannot_create_or_list_employees(db, client, employee_context, employee_password):
    headers = _login(client, employee_context.email, employee_password)
    assert client.get("/api/people/employees", headers=headers).status_code == 403
    assert client.post("/api/people/employees", headers=headers, json={}).status_code == 403


def test_http_create_employee_happy_path_and_login(db, client, manager_context, manager_password):
    headers = _login(client, manager_context.email, manager_password)
    department = client.post(
        "/api/people/departments", headers=headers, json={"name": "Sales"}
    ).json()
    designation = client.post(
        "/api/people/designations",
        headers=headers,
        json={"department_id": department["department_id"], "title": "Account Executive"},
    ).json()

    res = client.post(
        "/api/people/employees",
        headers=headers,
        json={
            "first_name": "New",
            "last_name": "Hire",
            "email": "new.hire@acme-hr-test.dev",
            "phone": None,
            "employee_code": "EMP-900",
            "department_id": department["department_id"],
            "designation_id": designation["designation_id"],
            "manager_employee_id": None,
            "joining_date": "2026-01-15",
            "password": "temp-password-1",
        },
    )
    assert res.status_code == 201
    body = res.json()
    assert body["employment_status"] == "ACTIVE"
    assert body["department_name"] == "Sales"
    assert body["designation_title"] == "Account Executive"

    # The HR-created credentials work against the login endpoint.
    login = client.post(
        "/api/auth/login", json={"email": "new.hire@acme-hr-test.dev", "password": "temp-password-1"}
    )
    assert login.status_code == 200


async def test_http_deactivate_revokes_login(db, client, manager_context, manager_password, employee_context, employee_password):
    svc = PeopleService(db)
    employee = await _employee_of(svc, employee_context)
    headers = _login(client, manager_context.email, manager_password)

    res = client.post(f"/api/people/employees/{employee.employee_id}/deactivate", headers=headers)
    assert res.status_code == 200
    assert res.json()["employment_status"] == "INACTIVE"

    # The deactivated employee can no longer authenticate.
    login = client.post(
        "/api/auth/login", json={"email": employee_context.email, "password": employee_password}
    )
    assert login.status_code == 401


def test_http_me_self_service(db, client, employee_context, employee_password):
    headers = _login(client, employee_context.email, employee_password)
    res = client.get("/api/people/me", headers=headers)
    assert res.status_code == 200
    body = res.json()
    assert body["email"] == employee_context.email
    assert body["first_name"] == "Sam"
    assert body["employment_status"] == "ACTIVE"


def test_http_me_requires_employee_role(db, client, candidate_context, candidate_password):
    headers = _login(client, candidate_context.email, candidate_password)
    assert client.get("/api/people/me", headers=headers).status_code == 403


async def test_http_employee_can_view_own_profile_but_not_others(
    db, client, manager_context, employee_context, employee_password
):
    svc = PeopleService(db)
    own = await _employee_of(svc, employee_context)
    other = await _employee_of(svc, manager_context)
    headers = _login(client, employee_context.email, employee_password)

    assert client.get(f"/api/people/employees/{own.employee_id}", headers=headers).status_code == 200
    assert client.get(f"/api/people/employees/{other.employee_id}", headers=headers).status_code == 403
