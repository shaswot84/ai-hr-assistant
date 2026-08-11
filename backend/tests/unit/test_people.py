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


def _make_dept_and_designation(svc, manager_context, *, dept: str | None = None, title="Specialist"):
    """Create a department + designation via the service and return them.

    Departments get a unique name per call unless one is passed explicitly, so
    tests can call this helper repeatedly without tripping the unique-name
    guard (the seeded fixtures already create "Human Resources").
    """
    import uuid

    dept = dept or f"People Ops {uuid.uuid4().hex[:6]}"
    department = svc.create_department(manager_context, name=dept)
    designation = svc.create_designation(
        manager_context, department_id=department.department_id, title=title
    )
    return department, designation


def _create_employee(svc, manager_context, *, email=None, code=None, **overrides):
    """Create an employee via the service with sensible (unique) defaults."""
    import uuid

    email = email or f"new.employee.{uuid.uuid4().hex[:6]}@acme-hr-test.dev"
    code = code or f"EMP-{uuid.uuid4().hex[:6]}"
    department, designation = _make_dept_and_designation(svc, manager_context)
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
    return svc.create_employee(manager_context, **defaults)


def _shortlist_application(db, manager_context, candidate_context):
    """Create a vacancy, apply as the candidate, and shortlist — return the Application."""
    recruitment = RecruitmentService(db)
    vacancy = recruitment.create_vacancy(
        manager_context,
        title="Senior Backend Engineer",
        department_name="Engineering",
        description="Build scalable APIs.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
    )
    application = recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    recruitment.decide_application(manager_context, application.application_id, approve=True)
    return application


def _employee_of(svc, context) -> Employee:
    """Resolve a UserContext to its Employee row."""
    return svc._identity.get_employee(context)


# ---- departments ---------------------------------------------------------


def test_create_department_requires_hr_admin(db, candidate_context):
    svc = PeopleService(db)
    with pytest.raises(PermissionError_):
        svc.create_department(candidate_context, name="Security")


def test_create_department_duplicate_conflicts(db, manager_context):
    svc = PeopleService(db)
    svc.create_department(manager_context, name="Operations")
    with pytest.raises(ConflictError_, match="already exists"):
        svc.create_department(manager_context, name="Operations")


# ---- designations --------------------------------------------------------


def test_create_designation_duplicate_conflicts(db, manager_context):
    svc = PeopleService(db)
    department, _ = _make_dept_and_designation(svc, manager_context, title="Specialist")
    with pytest.raises(ConflictError_, match="already exists"):
        svc.create_designation(manager_context, department_id=department.department_id, title="Specialist")


def test_list_designations_filters_by_department(db, manager_context):
    svc = PeopleService(db)
    dept_a, _ = _make_dept_and_designation(svc, manager_context, dept="Alpha", title="Role A")
    dept_b, _ = _make_dept_and_designation(svc, manager_context, dept="Beta", title="Role B")
    titles = {d.title for d in svc.list_designations(department_id=dept_a.department_id)}
    assert titles == {"Role A"}
    # The unfiltered list spans both departments (the fixture's seeded
    # "Human Resources" designation is present too, so use subset).
    all_ids = {d.department_id for d in svc.list_designations()}
    assert {dept_a.department_id, dept_b.department_id} <= all_ids


def test_list_designations_unknown_department_raises(db, manager_context):
    svc = PeopleService(db)
    with pytest.raises(NotFoundError_):
        svc.list_designations(department_id=uuid.UUID("00000000-0000-0000-0000-000000000000"))


# ---- employees: create ---------------------------------------------------


def test_create_employee_requires_hr_admin(db, manager_context, candidate_context):
    svc = PeopleService(db)
    department, designation = _make_dept_and_designation(svc, manager_context)
    with pytest.raises(PermissionError_):
        svc.create_employee(
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


def test_create_employee_provisions_person_user_and_employee(db, manager_context):
    svc = PeopleService(db)
    employee = _create_employee(svc, manager_context, email="prov@acme-hr-test.dev", code="EMP-101")
    db.refresh(employee)

    # All three rows exist, linked by person_id, and the login works.
    person = db.get(Person, employee.person_id)
    app_user = db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == person.person_id)
    )
    assert person.email == "prov@acme-hr-test.dev"
    assert app_user.coarse_role == "EMPLOYEE"
    assert app_user.status == "ACTIVE"
    assert employee.employment_status == "ACTIVE"
    assert employee in svc.list_employees()


def test_create_employee_duplicate_email_conflicts(db, manager_context):
    svc = PeopleService(db)
    _create_employee(svc, manager_context, email="dup@acme-hr-test.dev")
    with pytest.raises(ConflictError_, match="email already exists"):
        _create_employee(svc, manager_context, email="dup@acme-hr-test.dev", code="EMP-200")


def test_create_employee_duplicate_code_conflicts(db, manager_context):
    svc = PeopleService(db)
    _create_employee(svc, manager_context, code="EMP-300")
    with pytest.raises(ConflictError_, match="code already exists"):
        _create_employee(svc, manager_context, email="other@acme-hr-test.dev", code="EMP-300")


def test_create_employee_unknown_department_raises(db, manager_context):
    svc = PeopleService(db)
    _, designation = _make_dept_and_designation(svc, manager_context)
    with pytest.raises(NotFoundError_, match="Department not found"):
        _create_employee(
            svc,
            manager_context,
            department_id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
            designation_id=designation.designation_id,
        )


def test_create_employee_manager_must_be_active(db, manager_context, employee_context):
    svc = PeopleService(db)
    manager = _employee_of(svc, manager_context)
    # Deactivate the would-be manager, then try to assign them.
    svc.deactivate_employee(manager_context, manager.employee_id)
    with pytest.raises(ConflictError_, match="active employee"):
        _create_employee(svc, manager_context, manager_employee_id=manager.employee_id)


def test_create_employee_stores_email_lowercase_for_login(db, manager_context):
    svc = PeopleService(db)
    employee = _create_employee(svc, manager_context, email="Mixed.Case@Acme-Hr-Test.Dev")
    person = db.get(Person, employee.person_id)
    assert person.email == "mixed.case@acme-hr-test.dev"


# ---- employees: list / get / update --------------------------------------


def test_list_employees_filters_by_search_and_status(db, manager_context):
    svc = PeopleService(db)
    active = _create_employee(svc, manager_context, first_name="Zara", last_name="Active", code="EMP-400")
    _create_employee(svc, manager_context, first_name="Bob", last_name="Inactive", code="EMP-401")
    svc.deactivate_employee(manager_context, active.employee_id)

    # Search by name fragment.
    names = {f"{e.person.first_name} {e.person.last_name}" for e in svc.list_employees(search="zara")}
    assert names == {"Zara Active"}
    # Status filter: the deactivated one shows up under INACTIVE only (the
    # fixture's HR-manager employee is ACTIVE too, so compare by membership).
    inactive_codes = {e.employee_code for e in svc.list_employees(employment_status="INACTIVE")}
    assert inactive_codes == {"EMP-400"}
    active_codes = {e.employee_code for e in svc.list_employees(employment_status="ACTIVE")}
    assert "EMP-400" not in active_codes
    assert "EMP-401" in active_codes


def test_employee_can_view_own_profile_only(db, manager_context, employee_context):
    svc = PeopleService(db)
    own = _employee_of(svc, employee_context)
    other = _employee_of(svc, manager_context)

    assert svc.get_employee(employee_context, own.employee_id).employee_id == own.employee_id
    with pytest.raises(PermissionError_):
        svc.get_employee(employee_context, other.employee_id)
    # HR admins can view anyone.
    assert svc.get_employee(manager_context, own.employee_id).employee_id == own.employee_id
    assert svc.get_employee(manager_context, other.employee_id).employee_id == other.employee_id


def test_update_employee_patch_and_audit(db, manager_context):
    svc = PeopleService(db)
    employee = _create_employee(svc, manager_context)
    manager = _employee_of(svc, manager_context)

    updated = svc.update_employee(
        manager_context, employee.employee_id, first_name="Renamed", manager_employee_id=manager.employee_id
    )
    db.refresh(updated)
    assert updated.person.first_name == "Renamed"
    assert updated.manager_employee_id == manager.employee_id

    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "EMPLOYEE_UPDATED")
    ).first()
    assert entry is not None
    assert entry.new_state["manager_employee_id"] == str(manager.employee_id)


# ---- employees: deactivate -----------------------------------------------


def test_deactivate_employee_revokes_login(db, manager_context, employee_context):
    svc = PeopleService(db)
    employee = _employee_of(svc, employee_context)

    deactivated = svc.deactivate_employee(manager_context, employee.employee_id)
    assert deactivated.employment_status == "INACTIVE"

    # The ApplicationUser status flipped in the same transaction.
    app_user = db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == employee.person_id)
    )
    assert app_user.status == "INACTIVE"
    # Audit row records the change.
    entry = db.scalars(
        select(AuditLog).where(AuditLog.action == "EMPLOYEE_DEACTIVATED")
    ).first()
    assert entry is not None


def test_deactivate_employee_blocked_with_active_reports(db, manager_context, employee_context):
    svc = PeopleService(db)
    manager = _employee_of(svc, manager_context)
    report = _employee_of(svc, employee_context)
    # Make the employee report to the manager, then try to deactivate the manager.
    svc.update_employee(manager_context, report.employee_id, manager_employee_id=manager.employee_id)
    with pytest.raises(ConflictError_, match="manages active reports"):
        svc.deactivate_employee(manager_context, manager.employee_id)


# ---- hire handoff --------------------------------------------------------


def test_hire_candidate_requires_hr_admin(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = _shortlist_application(db, manager_context, candidate_context)
    department, designation = _make_dept_and_designation(svc, manager_context)
    with pytest.raises(PermissionError_):
        svc.hire_candidate(
            candidate_context,
            application.application_id,
            employee_code="EMP-500",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


def test_hire_candidate_creates_employee_and_links_candidate(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = _shortlist_application(db, manager_context, candidate_context)
    department, designation = _make_dept_and_designation(svc, manager_context)

    employee = svc.hire_candidate(
        manager_context,
        application.application_id,
        employee_code="EMP-500",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )
    db.refresh(employee)

    # Employee row exists on the candidate's Person.
    candidate = svc._identity.get_candidate_for_application(application)
    assert employee.person_id == candidate.person_id
    assert employee.employment_status == "ACTIVE"
    # Candidate is linked + marked hired.
    db.refresh(candidate)
    assert candidate.hired_employee_id == employee.employee_id
    assert candidate.candidate_status == "HIRED"
    assert candidate.hired_at is not None
    # Role flipped so the hiree can use the employee portal.
    app_user = db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == candidate.person_id)
    )
    assert app_user.coarse_role == "EMPLOYEE"
    # Audit row records the hire.
    entry = db.scalars(select(AuditLog).where(AuditLog.action == "CANDIDATE_HIRED")).first()
    assert entry is not None
    assert entry.new_state["employee_id"] == str(employee.employee_id)


def test_hire_candidate_requires_shortlisted(db, manager_context, candidate_context):
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    vacancy = recruitment.create_vacancy(
        manager_context,
        title="Junior Engineer",
        department_name="Engineering",
        description="Entry level.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
    )
    application = recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/b.pdf"
    )
    department, designation = _make_dept_and_designation(svc, manager_context)
    with pytest.raises(ConflictError_, match="SHORTLISTED"):
        svc.hire_candidate(
            manager_context,
            application.application_id,
            employee_code="EMP-501",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


def test_hire_candidate_already_hired_conflicts(db, manager_context, candidate_context):
    svc = PeopleService(db)
    application = _shortlist_application(db, manager_context, candidate_context)
    department, designation = _make_dept_and_designation(svc, manager_context)
    svc.hire_candidate(
        manager_context,
        application.application_id,
        employee_code="EMP-502",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )
    with pytest.raises(ConflictError_, match="already been hired"):
        svc.hire_candidate(
            manager_context,
            application.application_id,
            employee_code="EMP-503",
            department_id=department.department_id,
            designation_id=designation.designation_id,
            manager_employee_id=None,
            joining_date=date(2026, 2, 1),
        )


def test_hire_candidate_withdraws_other_open_applications(db, manager_context, candidate_context):
    """Hiring from one application withdraws the candidate's other open ones and emails them."""
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    v1 = recruitment.create_vacancy(
        manager_context, title="Senior Backend Engineer", department_name="Engineering",
        description="Build APIs.", employment_type="full_time", opening_date=None, closing_date=None,
    )
    v2 = recruitment.create_vacancy(
        manager_context, title="Data Analyst", department_name="Data",
        description="Analyze data.", employment_type="full_time", opening_date=None, closing_date=None,
    )
    hired_app = recruitment.apply(candidate_context, vacancy_id=v1.vacancy_id, cv_object_key="resumes/a.pdf")
    other_app = recruitment.apply(candidate_context, vacancy_id=v2.vacancy_id, cv_object_key="resumes/b.pdf")
    recruitment.decide_application(manager_context, hired_app.application_id, approve=True)
    recruitment.decide_application(manager_context, other_app.application_id, approve=True)

    department, designation = _make_dept_and_designation(svc, manager_context)
    svc.hire_candidate(
        manager_context,
        hired_app.application_id,
        employee_code="EMP-600",
        department_id=department.department_id,
        designation_id=designation.designation_id,
        manager_employee_id=None,
        joining_date=date(2026, 2, 1),
    )

    # The hired application stays SHORTLISTED; the sibling one is withdrawn.
    db.refresh(hired_app)
    db.refresh(other_app)
    assert hired_app.application_status == "SHORTLISTED"
    assert other_app.application_status == "WITHDRAWN"
    assert other_app.withdrawn_at is not None

    # One notification email was enqueued for the withdrawn application.
    jobs = db.scalars(
        select(OutboxJob).where(OutboxJob.job_type == "SEND_APPLICATION_WITHDRAWN")
    ).all()
    assert len(jobs) == 1
    assert jobs[0].payload["to_email"] == candidate_context.email
    assert jobs[0].payload["application_id"] == str(other_app.application_id)


def test_application_detail_exposes_hired_flag(
    db, client, manager_context, candidate_context, manager_password
):
    """The manager API marks an application as hired once the candidate was converted."""
    svc = PeopleService(db)
    recruitment = RecruitmentService(db)
    vacancy = recruitment.create_vacancy(
        manager_context, title="Product Designer", department_name="Design",
        description="Design products.", employment_type="full_time",
        opening_date=None, closing_date=None,
    )
    application = recruitment.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    recruitment.decide_application(manager_context, application.application_id, approve=True)
    department, designation = _make_dept_and_designation(svc, manager_context)
    svc.hire_candidate(
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


def test_http_deactivate_revokes_login(db, client, manager_context, manager_password, employee_context, employee_password):
    svc = PeopleService(db)
    employee = _employee_of(svc, employee_context)
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


def test_http_employee_can_view_own_profile_but_not_others(
    db, client, manager_context, employee_context, employee_password
):
    svc = PeopleService(db)
    own = _employee_of(svc, employee_context)
    other = _employee_of(svc, manager_context)
    headers = _login(client, employee_context.email, employee_password)

    assert client.get(f"/api/people/employees/{own.employee_id}", headers=headers).status_code == 200
    assert client.get(f"/api/people/employees/{other.employee_id}", headers=headers).status_code == 403
