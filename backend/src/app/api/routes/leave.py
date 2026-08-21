from __future__ import annotations

import uuid
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, require_role
from app.capabilities.leave import LeaveService, PermissionError_
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.domain.identity import Employee, Person
from app.domain.leave import LeaveRequest
from app.schemas.leave import (
    CompanyHolidayCreate,
    CompanyHolidayOut,
    LeaveBalanceOut,
    LeaveDecisionRequest,
    LeaveRequestCreate,
    LeaveRequestDetailOut,
    LeaveRequestOut,
    LeaveTypeCreate,
    LeaveTypeOut,
    TeamMemberOutOfOfficeOut,
    WorkingDaysCalculationOut,
    WorkingDaysCalculationRequest,
)

router = APIRouter(prefix="/api/leave", tags=["leave"])


def _svc(db: AsyncSession = Depends(get_db)) -> LeaveService:
    """FastAPI dependency that builds a LeaveService bound to the request's DB session."""
    return LeaveService(db)


async def _to_request_out(svc: LeaveService, request: LeaveRequest) -> LeaveRequestOut:
    """Build the shared request fields both the employee- and manager-facing schemas use."""
    leave_type = await svc._leave_types.get(request.leave_type_id)
    return LeaveRequestOut(
        leave_request_id=request.leave_request_id,
        request_number=request.request_number,
        leave_type_id=request.leave_type_id,
        leave_type_name=leave_type.leave_name if leave_type else "Unknown",
        start_date=request.start_date,
        end_date=request.end_date,
        total_days=request.total_days,
        is_half_day=bool(request.is_half_day),
        half_day_period=request.half_day_period,
        reason=request.reason,
        status=request.status,
        submitted_at=request.submitted_at,
        decided_at=request.decided_at,
    )


async def _to_request_detail_out(svc: LeaveService, request: LeaveRequest) -> LeaveRequestDetailOut:
    """Build a manager-facing request response, extended with the requesting employee's identity."""
    out = await _to_request_out(svc, request)
    employee = await svc._db.get(Employee, request.employee_id)
    person = await svc._db.get(Person, employee.person_id) if employee else None
    return LeaveRequestDetailOut(
        **out.model_dump(),
        employee_name=f"{person.first_name} {person.last_name}".strip() if person else None,
        employee_email=person.email if person else None,
    )


# ---- leave types --------------------------------------------------------


@router.get("/types", response_model=list[LeaveTypeOut])
async def list_leave_types(
    user: UserContext = Depends(get_current_user),
    svc: LeaveService = Depends(_svc),
):
    """List active leave types — any authenticated role (needed to build the request form)."""
    return await svc.list_leave_types()


@router.post("/types", response_model=LeaveTypeOut, status_code=status.HTTP_201_CREATED)
async def create_leave_type(
    body: LeaveTypeCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Create a new leave type (manager-only)."""
    try:
        return await svc.create_leave_type(
            user,
            leave_name=body.leave_name,
            description=body.description,
            default_days=body.default_days,
            requires_approval=body.requires_approval,
            is_paid=body.is_paid,
            max_consecutive_days=body.max_consecutive_days,
        )
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


# ---- company holidays ----------------------------------------------------


@router.get("/holidays", response_model=list[CompanyHolidayOut])
async def list_company_holidays(
    year: int | None = Query(default=None),
    user: UserContext = Depends(get_current_user),
    svc: LeaveService = Depends(_svc),
):
    """List official company holidays (accessible by all users)."""
    return await svc.list_company_holidays(year)


@router.post("/holidays", response_model=CompanyHolidayOut, status_code=status.HTTP_201_CREATED)
async def create_company_holiday(
    body: CompanyHolidayCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Create an official company holiday (manager-only)."""
    try:
        return await svc.create_company_holiday(
            user,
            name=body.name,
            holiday_date=body.holiday_date,
            description=body.description,
            is_recurring_yearly=body.is_recurring_yearly,
        )
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=409, detail=str(err)) from err


@router.delete("/holidays/{holiday_id}")
async def delete_company_holiday(
    holiday_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Delete a company holiday (manager-only)."""
    try:
        await svc.delete_company_holiday(user, holiday_id)
        return {"success": True}
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err


# ---- working days calculation -------------------------------------------


@router.post("/calculate-days", response_model=WorkingDaysCalculationOut)
async def calculate_leave_days(
    body: WorkingDaysCalculationRequest,
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Preview working days, weekend exclusions, and company holidays for a date range."""
    try:
        total_working, holidays_in_range = await svc.calculate_working_days(
            body.start_date,
            body.end_date,
            is_half_day=body.is_half_day,
            half_day_period=body.half_day_period,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    calendar_days = (body.end_date - body.start_date).days + 1 if not body.is_half_day else 1
    weekend_days = 0
    if not body.is_half_day:
        cur = body.start_date
        while cur <= body.end_date:
            if cur.weekday() >= 5:
                weekend_days += 1
            cur += timedelta(days=1)

    return WorkingDaysCalculationOut(
        start_date=body.start_date,
        end_date=body.end_date,
        total_working_days=total_working,
        calendar_days=calendar_days,
        weekend_days=weekend_days,
        holiday_days=len(holidays_in_range),
        holidays_in_range=[
            CompanyHolidayOut.model_validate(h) for h in holidays_in_range
        ],
    )


# ---- team out of office / calendar ---------------------------------------


@router.get("/team-out-of-office", response_model=list[TeamMemberOutOfOfficeOut])
async def list_team_out_of_office(
    department_id: uuid.UUID | None = Query(default=None),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """List team members out of office in a given date window."""
    try:
        entries = await svc.list_team_out_of_office(
            user,
            department_id=department_id,
            start_date=start_date,
            end_date=end_date,
        )
        return [TeamMemberOutOfOfficeOut(**e) for e in entries]
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err


# ---- balance --------------------------------------------------------------


@router.get("/balance", response_model=list[LeaveBalanceOut])
async def my_balance(
    year: int | None = None,
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Return the current employee's balance per leave type for the given (or current) year."""
    try:
        rows = await svc.list_my_balance(user, year)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    return [
        LeaveBalanceOut(
            leave_type_id=row["leave_type"].leave_type_id,
            leave_type_name=row["leave_type"].leave_name,
            year=row["year"],
            allocated_days=row["allocated_days"],
            used_days=row["used_days"],
            remaining_days=row["remaining_days"],
        )
        for row in rows
    ]


# ---- requests -------------------------------------------------------------


@router.post("/requests", response_model=LeaveRequestOut, status_code=status.HTTP_201_CREATED)
async def create_leave_request(
    body: LeaveRequestCreate,
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Submit a leave request (employee-only)."""
    try:
        request = await svc.request_leave(
            user,
            leave_type_id=body.leave_type_id,
            start_date=body.start_date,
            end_date=body.end_date,
            is_half_day=body.is_half_day,
            half_day_period=body.half_day_period,
            reason=body.reason,
        )
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return await _to_request_out(svc, request)


@router.get("/requests/mine", response_model=list[LeaveRequestOut])
async def my_leave_requests(
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """List the current employee's own leave requests."""
    try:
        requests = await svc.list_my_requests(user)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    return [await _to_request_out(svc, r) for r in requests]


@router.get("/requests/mine/{leave_request_id}", response_model=LeaveRequestOut)
async def my_leave_request(
    leave_request_id: uuid.UUID,
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Return one of the current employee's own leave requests by id."""
    try:
        request = await svc.get_my_request(user, leave_request_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return await _to_request_out(svc, request)


@router.post("/requests/mine/{leave_request_id}/cancel", response_model=LeaveRequestOut)
async def cancel_leave_request(
    leave_request_id: uuid.UUID,
    user: UserContext = Depends(require_role("EMPLOYEE", "HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Cancel one of the current employee's own still-pending leave requests."""
    try:
        request = await svc.cancel_request(user, leave_request_id)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return await _to_request_out(svc, request)


@router.get("/requests", response_model=list[LeaveRequestDetailOut])
async def all_leave_requests(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """List every leave request across all employees (manager-only)."""
    requests = await svc.list_all_requests(user)
    return [await _to_request_detail_out(svc, r) for r in requests]


@router.get("/requests/{leave_request_id}", response_model=LeaveRequestDetailOut)
async def leave_request_detail(
    leave_request_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Return a single leave request for manager review."""
    try:
        request = await svc.get_request_for_review(user, leave_request_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return await _to_request_detail_out(svc, request)


@router.post("/requests/{leave_request_id}/decision", response_model=LeaveRequestDetailOut)
async def decide_leave_request(
    leave_request_id: uuid.UUID,
    body: LeaveDecisionRequest,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: LeaveService = Depends(_svc),
):
    """Approve or reject a leave request (manager-only)."""
    if body.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'.")
    try:
        request = await svc.decide_request(user, leave_request_id, approve=body.action == "approve")
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return await _to_request_detail_out(svc, request)


