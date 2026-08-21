"""People (org directory) REST API — HR-side employee/department management.

Every mutating endpoint is HR_ADMIN-gated via `require_role`; the only
employee-facing endpoint is `GET /api/people/me` (self-service profile, also
available to HR admins since they are employees too).

Exception → HTTP mapping (kept in one place, at the call sites):
- `PermissionError_` → 403
- `NotFoundError_`   → 404
- `ConflictError_`   → 409
- `ValueError`       → 422
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession


from app.api.deps import get_current_user, require_role
from app.capabilities.people import (
    ConflictError_,
    NotFoundError_,
    PeopleService,
    PermissionError_,
)
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.domain.identity import Department, Designation, Employee, Person
from app.schemas.people import (
    DepartmentCreate,
    DepartmentOut,
    DesignationCreate,
    DesignationOut,
    EmployeeCreate,
    EmployeeOut,
    EmployeeUpdate,
    HireCandidateRequest,
)

router = APIRouter(prefix="/api/people", tags=["people"])


def _svc(db: AsyncSession = Depends(get_db)) -> PeopleService:
    """FastAPI dependency that builds a PeopleService bound to the request's DB session."""
    return PeopleService(db)


async def _department_name(svc: PeopleService, department_id: uuid.UUID) -> str | None:
    """Resolve a department id to its display name, or None if it no longer exists."""
    dept = await svc._db.get(Department, department_id)
    return dept.name if dept else None


async def _designation_title(svc: PeopleService, designation_id: uuid.UUID) -> str | None:
    """Resolve a designation id to its title, or None if it no longer exists."""
    designation = await svc._db.get(Designation, designation_id)
    return designation.title if designation else None


async def _manager_name(svc: PeopleService, manager_employee_id: uuid.UUID | None) -> str | None:
    """Resolve a manager's employee id to their display name, or None."""
    if manager_employee_id is None:
        return None
    manager = await svc._db.get(Employee, manager_employee_id)
    if manager is None:
        return None
    person = await svc._db.get(Person, manager.person_id)
    return f"{person.first_name} {person.last_name}".strip() if person else None


async def _employee_out(svc: PeopleService, employee) -> EmployeeOut:
    """Build an EmployeeOut, resolving department/designation/manager display names."""
    person = await svc._db.get(Person, employee.person_id)
    dept_name = await _department_name(svc, employee.department_id)
    desig_title = await _designation_title(svc, employee.designation_id)
    mgr_name = await _manager_name(svc, employee.manager_employee_id)
    return EmployeeOut(
        employee_id=employee.employee_id,
        employee_code=employee.employee_code,
        first_name=person.first_name if person else "",
        last_name=person.last_name if person else "",
        email=person.email if person else "",
        phone=person.phone if person else None,

        department_id=employee.department_id,
        department_name=dept_name,
        designation_id=employee.designation_id,
        designation_title=desig_title,
        manager_employee_id=employee.manager_employee_id,
        manager_name=mgr_name,
        joining_date=employee.joining_date,
        employment_status=employee.employment_status,
        created_at=employee.created_at,
        updated_at=employee.updated_at,
    )


async def _designation_out(svc: PeopleService, designation) -> DesignationOut:
    """Build a DesignationOut with its department name attached."""
    dept_name = await _department_name(svc, designation.department_id)
    return DesignationOut(
        designation_id=designation.designation_id,
        department_id=designation.department_id,
        department_name=dept_name,
        title=designation.title,
        level=designation.level,
        is_active=designation.is_active,
    )


# ---- departments --------------------------------------------------------


@router.get("/departments", response_model=list[DepartmentOut])
async def list_departments(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """List all departments (HR only)."""
    return await svc.list_departments()


@router.post("/departments", response_model=DepartmentOut, status_code=status.HTTP_201_CREATED)
async def create_department(
    body: DepartmentCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Create a department (HR only)."""
    try:
        return await svc.create_department(user, name=body.name)
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


# ---- designations -------------------------------------------------------


@router.get("/designations", response_model=list[DesignationOut])
async def list_designations(
    department_id: uuid.UUID | None = None,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """List designations, optionally filtered to one department (HR only)."""
    try:
        designations = await svc.list_designations(department_id=department_id)
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return [await _designation_out(svc, d) for d in designations]


@router.post("/designations", response_model=DesignationOut, status_code=status.HTTP_201_CREATED)
async def create_designation(
    body: DesignationCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Create a designation in a department (HR only)."""
    try:
        designation = await svc.create_designation(
            user,
            department_id=body.department_id,
            title=body.title,
            level=body.level,
        )
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return await _designation_out(svc, designation)


# ---- employees ----------------------------------------------------------


@router.get("/employees", response_model=list[EmployeeOut])
async def list_employees(
    search: str | None = Query(None, description="Free-text filter on name/email/code"),
    department_id: uuid.UUID | None = None,
    employment_status: str | None = None,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """List employees with optional filters (HR only)."""
    try:
        employees = await svc.list_employees(
            search=search,
            department_id=department_id,
            employment_status=employment_status,
        )
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return [await _employee_out(svc, e) for e in employees]


@router.get("/employees/{employee_id}", response_model=EmployeeOut)
async def get_employee(
    employee_id: uuid.UUID,
    user: UserContext = Depends(get_current_user),
    svc: PeopleService = Depends(_svc),
):
    """Fetch one employee. HR may view anyone; an employee may view themselves."""
    try:
        employee = await svc.get_employee(user, employee_id)
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    return await _employee_out(svc, employee)


@router.post("/employees", response_model=EmployeeOut, status_code=status.HTTP_201_CREATED)
async def create_employee(
    body: EmployeeCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Create an employee with HR-provided login credentials (HR only)."""
    try:
        employee = await svc.create_employee(
            user,
            first_name=body.first_name,
            last_name=body.last_name,
            email=body.email,
            phone=body.phone,
            employee_code=body.employee_code,
            department_id=body.department_id,
            designation_id=body.designation_id,
            manager_employee_id=body.manager_employee_id,
            joining_date=body.joining_date,
            password=body.password,
        )
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return await _employee_out(svc, employee)


@router.put("/employees/{employee_id}", response_model=EmployeeOut)
async def update_employee(
    employee_id: uuid.UUID,
    body: EmployeeUpdate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Update an employee's profile fields (patch semantics, HR only)."""
    try:
        employee = await svc.update_employee(user, employee_id, **body.model_dump(exclude_unset=True))
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err)) from err
    return await _employee_out(svc, employee)


@router.post("/employees/{employee_id}/deactivate", response_model=EmployeeOut)
async def deactivate_employee(
    employee_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Deactivate an employee and revoke their login (HR only)."""
    try:
        employee = await svc.deactivate_employee(user, employee_id)
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return await _employee_out(svc, employee)


# ---- hire handoff -------------------------------------------------------


@router.post(
    "/candidates/{application_id}/hire",
    response_model=EmployeeOut,
    status_code=status.HTTP_201_CREATED,
)
async def hire_candidate(
    application_id: uuid.UUID,
    body: HireCandidateRequest,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Hire a shortlisted candidate from their application (HR only)."""
    try:
        employee = await svc.hire_candidate(
            user,
            application_id,
            employee_code=body.employee_code,
            department_id=body.department_id,
            designation_id=body.designation_id,
            manager_employee_id=body.manager_employee_id,
            joining_date=body.joining_date,
        )
    except NotFoundError_ as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    except ConflictError_ as err:
        raise HTTPException(status_code=409, detail=str(err)) from err
    return await _employee_out(svc, employee)


# ---- self-service -------------------------------------------------------


@router.get("/me", response_model=EmployeeOut)
async def my_profile(
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: PeopleService = Depends(_svc),
):
    """Return the current user's own employee profile (employee portal self-service)."""
    return await _employee_out(svc, await svc.my_profile(user))

