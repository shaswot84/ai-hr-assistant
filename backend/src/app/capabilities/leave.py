from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Department, Designation, Employee, Person
from app.domain.leave import CompanyHoliday, LeaveBalance, LeaveRequest, LeaveType
from app.repositories.audit import AuditRepo
from app.repositories.leave import (
    CompanyHolidayRepo,
    LeaveBalanceRepo,
    LeaveRequestRepo,
    LeaveTypeRepo,
)
from app.repositories.outbox import OutboxRepo
from app.services.identity import IdentityService
from app.shared.clock import Clock, get_clock

# A decision is only ever valid from PENDING — once approved/rejected an
# employee's request is terminal for this sprint (no re-review), mirroring
# recruitment's DECIDABLE_STATUSES so a decision can never be replayed into
# a second notification email or silently overwrite a prior outcome.
DECIDABLE_STATUSES = {"PENDING"}


class PermissionError_(Exception):
    """Raised when a caller lacks the authority to perform a leave operation."""


class LeaveService:
    """Deterministic leave-management business logic (capability layer)."""

    def __init__(self, db: AsyncSession, clock: Clock | None = None) -> None:
        """Bind the service to an async DB session and build its repositories."""
        self._db = db
        self._clock = clock or get_clock()
        self._leave_types = LeaveTypeRepo(db)
        self._balances = LeaveBalanceRepo(db)
        self._requests = LeaveRequestRepo(db)
        self._holidays = CompanyHolidayRepo(db)
        self._outbox = OutboxRepo(db, clock=self._clock)
        self._audit = AuditRepo(db, clock=self._clock)
        self._identity = IdentityService(db)

    # ---- leave types (manager-configured, employee-readable) ---------

    async def create_leave_type(
        self,
        actor: UserContext,
        *,
        leave_name: str,
        description: str | None,
        default_days: Decimal,
        requires_approval: bool,
        is_paid: bool,
        max_consecutive_days: int | None,
    ) -> LeaveType:
        """Create a new leave type (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can create leave types.")
        name = leave_name.strip()
        existing = await self._leave_types.get_by_name_ci(name)
        if existing is not None:
            raise ValueError(
                f"A leave type named '{existing.leave_name}' already exists "
                "(names are case-insensitive)."
            )
        leave_type = LeaveType(
            leave_name=name,
            description=description,
            default_days=default_days,
            requires_approval=requires_approval,
            is_paid=is_paid,
            max_consecutive_days=max_consecutive_days,
            status="ACTIVE",
        )
        await self._leave_types.create(leave_type)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="LEAVE_TYPE_CREATED",
            target_type="leave_type",
            target_id=leave_type.leave_type_id,
            new_state={"leave_name": leave_type.leave_name},
        )
        await self._db.commit()
        return leave_type

    async def list_leave_types(self) -> list[LeaveType]:
        """List active leave types — every role can read these (needed to build the request form)."""
        return await self._leave_types.list_active()

    # ---- company holidays (manager-configured, employee-readable) ---

    async def create_company_holiday(
        self,
        actor: UserContext,
        *,
        name: str,
        holiday_date: date,
        description: str | None = None,
        is_recurring_yearly: bool = False,
    ) -> CompanyHoliday:
        """Create a new official company holiday (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can create company holidays.")
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Holiday name cannot be empty.")
        existing = await self._holidays.get_by_date(holiday_date)
        if existing is not None:
            raise ValueError(
                f"A company holiday already exists on {holiday_date} ('{existing.name}')."
            )

        now = self._clock.now()
        holiday = CompanyHoliday(
            name=clean_name,
            holiday_date=holiday_date,
            description=description.strip() if description else None,
            is_recurring_yearly=is_recurring_yearly,
            created_at=now,
            updated_at=now,
        )
        await self._holidays.create(holiday)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="COMPANY_HOLIDAY_CREATED",
            target_type="company_holiday",
            target_id=holiday.holiday_id,
            new_state={"name": holiday.name, "holiday_date": str(holiday.holiday_date)},
        )
        await self._db.commit()
        return holiday

    async def list_company_holidays(self, year: int | None = None) -> list[CompanyHoliday]:
        """List official company holidays, optionally filtering for a given year."""
        return await self._holidays.list_all(year)

    async def delete_company_holiday(self, actor: UserContext, holiday_id: uuid.UUID) -> None:
        """Delete a company holiday (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can delete company holidays.")
        holiday = await self._holidays.get(holiday_id)
        if holiday is None:
            raise ValueError("Company holiday not found.")
        await self._holidays.delete(holiday)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="COMPANY_HOLIDAY_DELETED",
            target_type="company_holiday",
            target_id=holiday.holiday_id,
            previous_state={"name": holiday.name, "holiday_date": str(holiday.holiday_date)},
        )
        await self._db.commit()

    # ---- balances ------------------------------------------------------

    async def list_my_balance(self, actor: UserContext, year: int | None = None) -> list[dict]:
        """Return the current employee's allocated/used/remaining days per leave type."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees have a leave balance.")
        employee = await self._identity.get_employee(actor)
        return await self._balance_rows(employee, year or self._clock.today().year)

    async def get_employee_balance(
        self, actor: UserContext, employee_code: str, year: int | None = None
    ) -> list[dict]:
        """Return ANOTHER employee's balance grid (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can view employee leave balances.")
        target = employee_code.strip()
        stmt = select(Employee).where(Employee.employee_code.ilike(target))
        employee = await self._db.scalar(stmt)
        if employee is None:
            words = target.split()
            if len(words) >= 2:
                p_stmt = select(Person).where(
                    Person.first_name.ilike(f"%{words[0]}%"),
                    Person.last_name.ilike(f"%{words[-1]}%"),
                )
            else:
                p_stmt = select(Person).where(
                    (Person.first_name.ilike(f"%{target}%"))
                    | (Person.last_name.ilike(f"%{target}%"))
                    | (Person.email.ilike(f"%{target}%"))
                )
            person = await self._db.scalar(p_stmt)
            if person is not None:
                employee = await self._db.scalar(select(Employee).where(Employee.person_id == person.person_id))
        if employee is None:
            raise ValueError(f"Employee '{employee_code}' not found.")
        return await self._balance_rows(employee, year or self._clock.today().year)

    async def list_all_employee_balances(
        self, actor: UserContext, year: int | None = None
    ) -> list[dict]:
        """Return all active employees' leave balances with reporting hierarchy (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can view all employee leave balances.")

        target_year = year or self._clock.today().year
        stmt = (
            select(Employee, Person, Department, Designation)
            .join(Person, Employee.person_id == Person.person_id)
            .outerjoin(Department, Employee.department_id == Department.department_id)
            .outerjoin(Designation, Employee.designation_id == Designation.designation_id)
            .where(Employee.employment_status == "ACTIVE")
            .order_by(Employee.employee_code)
        )
        result = await self._db.execute(stmt)
        records = result.all()

        results = []
        for emp, person, dept, desig in records:
            raw_rows = await self._balance_rows(emp, target_year)
            balances = [
                {
                    "leave_type_name": row["leave_type"].leave_name,
                    "year": row["year"],
                    "allocated_days": str(row["allocated_days"]),
                    "used_days": str(row["used_days"]),
                    "remaining_days": str(row["remaining_days"]),
                }
                for row in raw_rows
            ]
            results.append(
                {
                    "employee_id": str(emp.employee_id),
                    "employee_code": emp.employee_code,
                    "employee_name": f"{person.first_name} {person.last_name}".strip(),
                    "employee_email": person.email,
                    "manager_employee_id": str(emp.manager_employee_id) if emp.manager_employee_id else None,
                    "department_name": dept.name if dept else None,
                    "designation_title": desig.title if desig else None,
                    "year": target_year,
                    "balances": balances,
                }
            )
        return results

    async def _balance_rows(self, employee: Employee, target_year: int) -> list[dict]:
        """The allocated/used/remaining grid for one employee in one year."""
        existing = {b.leave_type_id: b for b in await self._balances.list_for_employee(employee.employee_id, target_year)}

        rows = []
        for leave_type in await self._leave_types.list_active():
            balance = existing.get(leave_type.leave_type_id)
            allocated = balance.allocated_days if balance else leave_type.default_days
            used = balance.used_days if balance else Decimal(0)
            rows.append(
                {
                    "leave_type": leave_type,
                    "year": target_year,
                    "allocated_days": allocated,
                    "used_days": used,
                    "remaining_days": allocated - used,
                }
            )
        return rows

    async def _get_or_create_balance(
        self, employee_id: uuid.UUID, leave_type: LeaveType, year: int
    ) -> LeaveBalance:
        """Return the employee's balance row for a type/year, creating it from the type's default on first use."""
        balance = await self._balances.get(employee_id, leave_type.leave_type_id, year)
        if balance is None:
            balance = LeaveBalance(
                employee_id=employee_id,
                leave_type_id=leave_type.leave_type_id,
                year=year,
                allocated_days=leave_type.default_days,
                used_days=Decimal(0),
                updated_at=self._clock.now(),
            )
            await self._balances.create(balance)
        return balance

    # ---- working days calculation ---------------------------------------

    async def calculate_working_days(
        self,
        start_date: date,
        end_date: date,
        *,
        is_half_day: bool = False,
        half_day_period: str | None = None,
    ) -> tuple[Decimal, list[CompanyHoliday]]:
        """Calculate working days between start_date and end_date (inclusive)."""
        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")

        years = set(range(start_date.year, end_date.year + 1))
        all_holidays: list[CompanyHoliday] = []
        for y in years:
            all_holidays.extend(await self._holidays.list_all(y))

        unique_holidays = {h.holiday_id: h for h in all_holidays}.values()
        holiday_map: dict[date, CompanyHoliday] = {}
        for h in unique_holidays:
            if h.is_recurring_yearly:
                for y in years:
                    try:
                        rec_date = date(y, h.holiday_date.month, h.holiday_date.day)
                        holiday_map[rec_date] = h
                    except ValueError:
                        pass
            else:
                holiday_map[h.holiday_date] = h

        if is_half_day:
            if start_date != end_date:
                raise ValueError("Half-day leave start and end dates must be the same.")
            if start_date.weekday() >= 5:
                raise ValueError("Cannot request half-day leave on a weekend.")
            if start_date in holiday_map:
                h = holiday_map[start_date]
                h_type = "an annual recurring company holiday" if h.is_recurring_yearly else "a custom company holiday created by the company"
                raise ValueError(
                    f"Cannot request leave on {start_date}: '{h.name}' is {h_type}. The office is closed on this day, so no leave is required."
                )
            if half_day_period not in ("MORNING", "AFTERNOON"):
                raise ValueError("Half-day period must be either 'MORNING' or 'AFTERNOON'.")
            return Decimal("0.5"), []

        working_days = 0
        holidays_in_range: list[CompanyHoliday] = []
        seen_holidays: set[uuid.UUID] = set()

        cur = start_date
        while cur <= end_date:
            is_weekend = cur.weekday() >= 5
            holiday = holiday_map.get(cur)
            if not is_weekend:
                if holiday is not None:
                    if holiday.holiday_id not in seen_holidays:
                        holidays_in_range.append(holiday)
                        seen_holidays.add(holiday.holiday_id)
                else:
                    working_days += 1
            cur += timedelta(days=1)

        return Decimal(str(working_days)), holidays_in_range

    # ---- requests --------------------------------------------------------

    async def request_leave(
        self,
        actor: UserContext,
        *,
        leave_type_id: uuid.UUID,
        start_date: date,
        end_date: date,
        is_half_day: bool = False,
        half_day_period: str | None = None,
        reason: str | None = None,
    ) -> LeaveRequest:
        """Submit a leave request; validates working days, max-consecutive-days, and balance before creating it."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees can request leave.")
        employee = await self._identity.get_employee(actor)
        leave_type = await self._leave_types.get(leave_type_id)
        if leave_type is None or leave_type.status != "ACTIVE":
            raise ValueError("Leave type not found.")
        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")
        if start_date < self._clock.today():
            raise ValueError("Leave cannot start in the past.")

        total_days, holidays_in_range = await self.calculate_working_days(
            start_date, end_date, is_half_day=is_half_day, half_day_period=half_day_period
        )
        if total_days <= Decimal("0"):
            if holidays_in_range:
                h_details = [
                    f"'{h.name}' ({'annual recurring holiday' if h.is_recurring_yearly else 'custom company holiday created by the company'})"
                    for h in holidays_in_range
                ]
                raise ValueError(
                    f"The selected period ({start_date} to {end_date}) falls on company holiday(s): {', '.join(h_details)}. "
                    f"The office is closed on these days, so no leave deduction or request is needed."
                )
            raise ValueError(
                f"The selected period ({start_date} to {end_date}) falls entirely on weekends. No working days to request leave for."
            )

        await self.check_request_conflicts(
            actor,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            is_half_day=is_half_day,
            half_day_period=half_day_period,
        )

        year = start_date.year
        balance = await self._get_or_create_balance(employee.employee_id, leave_type, year)
        remaining = balance.allocated_days - balance.used_days
        if total_days > remaining:
            raise ValueError(
                f"Not enough {leave_type.leave_name} balance: {remaining} day(s) remaining, "
                f"{total_days} requested."
            )

        now = self._clock.now()
        count = await self._requests.count_for_year(year)
        request_number = f"LR-{year}-{count + 1:03d}"
        request = LeaveRequest(
            request_number=request_number,
            employee_id=employee.employee_id,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            is_half_day=is_half_day,
            half_day_period=half_day_period if is_half_day else None,
            reason=reason,
            status="PENDING",
            version=1,
            submitted_at=now,
            updated_at=now,
        )
        await self._requests.create(request)

        duration_desc = f"{total_days} day(s)"
        if is_half_day and half_day_period:
            duration_desc = f"0.5 day ({half_day_period.lower()})"

        employee_email = await self._employee_email(employee)
        await self._outbox.enqueue(
            "SEND_LEAVE_REQUEST_RECEIVED",
            {
                "leave_request_id": str(request.leave_request_id),
                "to_email": employee_email,
                "subject": f"Leave request received: {request_number}",
                "body": (
                    f"Your {leave_type.leave_name} request ({start_date} to {end_date}, "
                    f"{duration_desc}) has been submitted and is pending approval."
                ),
            },
            aggregate_type="leave_request",
            aggregate_id=request.leave_request_id,
        )
        approver_email = await self._approver_email(employee)
        if approver_email:
            emp_name = await self._employee_display_name(employee)
            await self._outbox.enqueue(
                "SEND_NEW_LEAVE_REQUEST_ALERT",
                {
                    "leave_request_id": str(request.leave_request_id),
                    "to_email": approver_email,
                    "subject": f"New leave request: {request_number}",
                    "body": (
                        f"{emp_name} submitted a "
                        f"{leave_type.leave_name} request ({start_date} to {end_date}, "
                        f"{duration_desc}). Review it in the manager portal."
                    ),
                },
                aggregate_type="leave_request",
                aggregate_id=request.leave_request_id,
            )

        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="LEAVE_REQUEST_CREATED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            new_state={"status": "PENDING"},
        )
        await self._db.commit()
        return request

    async def check_request_conflicts(
        self,
        actor: UserContext,
        *,
        leave_type_id: uuid.UUID,
        start_date: date,
        end_date: date,
        is_half_day: bool = False,
        half_day_period: str | None = None,
    ) -> None:
        """Reject a request that collides with the employee's live leave."""
        employee = await self._identity.get_employee(actor)
        leave_type = await self._leave_types.get(leave_type_id)
        if leave_type is None or leave_type.status != "ACTIVE":
            raise ValueError("Leave type not found.")

        active_requests = await self._active_requests(employee.employee_id)
        total_days, _ = await self.calculate_working_days(
            start_date, end_date, is_half_day=is_half_day, half_day_period=half_day_period
        )
        if leave_type.max_consecutive_days and total_days > leave_type.max_consecutive_days:
            raise ValueError(
                f"{leave_type.leave_name} cannot be taken for more than "
                f"{leave_type.max_consecutive_days} consecutive day(s)."
            )

        overlap = self._overlapping_request(
            active_requests,
            start_date,
            end_date,
            is_half_day=is_half_day,
            half_day_period=half_day_period,
        )
        if overlap is not None:
            leave_name = await self._leave_name_of(overlap)
            if overlap.is_half_day and is_half_day and overlap.start_date == start_date:
                period_str = f" ({overlap.half_day_period})" if overlap.half_day_period else ""
                raise ValueError(
                    f"Dates overlap your existing "
                    f"{leave_name} request "
                    f"({overlap.start_date}{period_str})."
                )
            raise ValueError(
                f"Dates overlap your existing "
                f"{leave_name} request "
                f"({overlap.start_date} to {overlap.end_date})."
            )

        if leave_type.max_consecutive_days:
            run_days = self._consecutive_run_days(
                [r for r in active_requests if r.leave_type_id == leave_type_id],
                start_date,
                end_date,
            )
            if run_days > leave_type.max_consecutive_days:
                raise ValueError(
                    f"{leave_type.leave_name} cannot be taken for more than "
                    f"{leave_type.max_consecutive_days} consecutive day(s) "
                    f"in one run."
                )

    async def list_my_requests(self, actor: UserContext) -> list[LeaveRequest]:
        """List the current employee's own leave requests."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees can view their own leave requests.")
        employee = await self._identity.get_employee(actor)
        return await self._requests.list_for_employee(employee.employee_id)

    async def get_my_request(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Fetch one of the current employee's own leave requests, or raise if not theirs/not found."""
        employee = await self._identity.get_employee(actor)
        request = await self._requests.get_for_employee(leave_request_id, employee.employee_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return request

    async def get_my_request_by_reference(
        self, actor: UserContext, request_number: str
    ) -> LeaveRequest:
        """Fetch one of the current employee's own leave requests by its LR-YYYY-XXX reference."""
        employee = await self._identity.get_employee(actor)
        request = await self._requests.get_by_request_number(request_number.strip().upper())
        if request is None or request.employee_id != employee.employee_id:
            raise ValueError("Leave request not found.")
        return request

    async def get_request_by_number(self, actor: UserContext, request_number: str) -> LeaveRequest:
        """Fetch any employee's leave request by reference (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review leave requests.")
        request = await self._requests.get_by_request_number(request_number.strip().upper())
        if request is None:
            raise ValueError("Leave request not found.")
        return request

    async def cancel_request(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Cancel one of the current employee's own still-pending requests (by id)."""
        employee = await self._identity.get_employee(actor)
        request = await self._requests.get_for_employee(leave_request_id, employee.employee_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return await self._cancel_request(actor, request)

    async def cancel_request_by_reference(
        self, actor: UserContext, request_number: str
    ) -> LeaveRequest:
        """Cancel one of the current employee's own still-pending requests (by reference)."""
        employee = await self._identity.get_employee(actor)
        request = await self._requests.get_by_request_number(request_number.strip().upper())
        if request is None or request.employee_id != employee.employee_id:
            raise ValueError("Leave request not found.")
        return await self._cancel_request(actor, request)

    async def _cancel_request(self, actor: UserContext, request: LeaveRequest) -> LeaveRequest:
        """The shared cancel body: PENDING-only, audit, commit."""
        if request.status != "PENDING":
            raise ValueError(f"Only pending requests can be cancelled (status={request.status}).")

        now = self._clock.now()
        previous_status = request.status
        request.status = "CANCELLED"
        request.version += 1
        request.updated_at = now
        await self._requests.save(request)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="LEAVE_REQUEST_CANCELLED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            previous_state={"status": previous_status},
            new_state={"status": "CANCELLED"},
        )
        await self._db.commit()
        return request

    async def list_all_requests(self, actor: UserContext) -> list[LeaveRequest]:
        """List every leave request across all employees (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review leave requests.")
        return await self._requests.list_all()

    async def get_request_for_review(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Fetch a single leave request for manager review, or raise if not found."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review leave requests.")
        request = await self._requests.get(leave_request_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return request

    async def decide_request(
        self, actor: UserContext, leave_request_id: uuid.UUID, *, approve: bool
    ) -> LeaveRequest:
        """Approve or reject a leave request by id; approving books the days against the employee's balance."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can decide leave requests.")
        request = await self._requests.get(leave_request_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return await self._decide_request(actor, request, approve=approve)

    async def decide_request_by_reference(
        self, actor: UserContext, request_number: str, *, approve: bool
    ) -> LeaveRequest:
        """Approve or reject a leave request by its LR-YYYY-XXX reference (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can decide leave requests.")
        request = await self._requests.get_by_request_number(request_number.strip().upper())
        if request is None:
            raise ValueError("Leave request not found.")
        return await self._decide_request(actor, request, approve=approve)

    async def _decide_request(
        self, actor: UserContext, request: LeaveRequest, *, approve: bool
    ) -> LeaveRequest:
        """The shared decision body used by the id and reference paths."""
        if request.status not in DECIDABLE_STATUSES:
            raise ValueError(
                f"Leave request has already been decided (status={request.status})."
            )

        decider = await self._identity.get_employee(actor)
        now = self._clock.now()
        previous_status = request.status
        request.status = "APPROVED" if approve else "REJECTED"
        request.decided_by_employee_id = decider.employee_id
        request.decided_at = now
        request.version += 1
        request.updated_at = now
        await self._requests.save(request)

        if approve:
            leave_type = await self._leave_types.get(request.leave_type_id)
            balance = await self._get_or_create_balance(
                request.employee_id, leave_type, request.start_date.year
            )
            balance.used_days = balance.used_days + request.total_days
            balance.updated_at = now
            await self._balances.save(balance)

        job_type, subject, body = await self._build_decision_email(request, approve=approve)
        employee = await self._db.get(Employee, request.employee_id)
        employee_email = await self._employee_email(employee) if employee else ""
        await self._outbox.enqueue(
            job_type,
            {
                "leave_request_id": str(request.leave_request_id),
                "to_email": employee_email,
                "subject": subject,
                "body": body,
            },
            aggregate_type="leave_request",
            aggregate_id=request.leave_request_id,
        )
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="LEAVE_REQUEST_APPROVED" if approve else "LEAVE_REQUEST_REJECTED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            previous_state={"status": previous_status},
            new_state={"status": request.status},
        )
        await self._db.commit()
        return request

    # ---- team out of office / calendar -------------------------------

    async def list_team_out_of_office(
        self,
        actor: UserContext,
        *,
        department_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[dict]:
        """List team members who are out of office (approved/pending leaves) in a date window."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees and managers can view team calendar.")

        target_dept_id = department_id
        if actor.coarse_role == "EMPLOYEE" and target_dept_id is None:
            try:
                employee = await self._identity.get_employee(actor)
                target_dept_id = employee.department_id
            except Exception:
                target_dept_id = None

        query_start = start_date or self._clock.today()
        query_end = end_date or (query_start + timedelta(days=30))

        requests = await self._requests.list_team_out_of_office(
            department_id=target_dept_id,
            start_date=query_start,
            end_date=query_end,
        )

        results = []
        for req in requests:
            req_emp = await self._db.get(Employee, req.employee_id)
            if not req_emp:
                continue
            person = await self._db.get(Person, req_emp.person_id)
            emp_name = f"{person.first_name} {person.last_name}".strip() if person else "Unknown"
            dept = await self._db.get(Department, req_emp.department_id) if req_emp.department_id else None
            dept_name = dept.name if dept else None
            leave_type = await self._leave_types.get(req.leave_type_id)
            leave_name = leave_type.leave_name if leave_type else "Unknown"

            results.append({
                "leave_request_id": req.leave_request_id,
                "employee_id": req.employee_id,
                "employee_name": emp_name,
                "department_id": req_emp.department_id,
                "department_name": dept_name,
                "leave_type_name": leave_name,
                "start_date": req.start_date,
                "end_date": req.end_date,
                "total_days": req.total_days,
                "is_half_day": bool(req.is_half_day),
                "half_day_period": req.half_day_period,
                "status": req.status,
            })
        return results

    # ---- helpers -----------------------------------------------------

    async def _active_requests(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        """The employee's current, live leave requests — PENDING or APPROVED."""
        return [
            r
            for r in await self._requests.list_for_employee(employee_id)
            if r.status in ("PENDING", "APPROVED")
        ]

    def _overlapping_request(
        self,
        requests: list[LeaveRequest],
        start_date: date,
        end_date: date,
        *,
        is_half_day: bool = False,
        half_day_period: str | None = None,
    ) -> LeaveRequest | None:
        """Return the first request whose date range and period intersects."""
        for existing in requests:
            if existing.start_date <= end_date and existing.end_date >= start_date:
                if not existing.is_half_day or not is_half_day:
                    return existing
                if existing.start_date == start_date:
                    if (
                        not existing.half_day_period
                        or not half_day_period
                        or existing.half_day_period == half_day_period
                    ):
                        return existing
                else:
                    return existing
        return None

    def _consecutive_run_days(
        self, requests: list[LeaveRequest], start_date: date, end_date: date
    ) -> int:
        """Total days of the contiguous leave run this new request joins."""
        runs: list[list[date]] = []
        for existing in requests:
            if (
                existing.end_date + timedelta(days=1) < start_date
                or existing.start_date - timedelta(days=1) > end_date
            ):
                continue
            runs.append([existing.start_date, existing.end_date])
        runs.append([start_date, end_date])

        merged = True
        while merged:
            merged = False
            for i in range(len(runs)):
                for j in range(i + 1, len(runs)):
                    a, b = runs[i], runs[j]
                    if (
                        a[0] <= b[1] + timedelta(days=1)
                        and b[0] <= a[1] + timedelta(days=1)
                    ):
                        runs[i] = [min(a[0], b[0]), max(a[1], b[1])]
                        runs.pop(j)
                        merged = True
                        break
                if merged:
                    break

        run = max(runs, key=lambda r: (r[1] - r[0]).days)
        return (run[1] - run[0]).days + 1

    async def _leave_name_of(self, request: LeaveRequest) -> str:
        """Resolve a request's leave type name, or a generic fallback."""
        leave_type = await self._leave_types.get(request.leave_type_id)
        return leave_type.leave_name if leave_type else "leave"

    async def _actor_user_id(self, actor: UserContext) -> uuid.UUID | None:
        """Resolve the actor's application_user id for audit records (best-effort)."""
        try:
            return (await self._identity._get_app_user(actor)).user_id
        except Exception:  # noqa: BLE001
            return None

    async def _employee_email(self, employee: Employee) -> str:
        """Resolve an employee's email address."""
        person = await self._db.get(Person, employee.person_id)
        return person.email if person else ""

    async def _employee_display_name(self, employee: Employee) -> str:
        """Resolve an employee's display name, or a generic fallback."""
        person = await self._db.get(Person, employee.person_id)
        return f"{person.first_name} {person.last_name}".strip() if person else "An employee"

    async def _approver_email(self, employee: Employee) -> str:
        """Resolve who should be notified of this employee's leave activity."""
        if employee.manager_employee_id:
            manager = await self._db.get(Employee, employee.manager_employee_id)
            if manager is not None:
                return await self._employee_email(manager)
        stmt = select(ApplicationUser).where(ApplicationUser.coarse_role == "HR_ADMIN").limit(1)
        admin = await self._db.scalar(stmt)
        if admin is None:
            return ""
        person = await self._db.get(Person, admin.person_id)
        return person.email if person else ""

    async def _build_decision_email(
        self, request: LeaveRequest, *, approve: bool
    ) -> tuple[str, str, str]:
        """Build the outbox job type, subject, and body for an approve/reject notification."""
        leave_type = await self._leave_types.get(request.leave_type_id)
        name = leave_type.leave_name if leave_type else "leave"
        if approve:
            return (
                "SEND_LEAVE_APPROVAL_EMAIL",
                f"Leave approved: {request.request_number}",
                (
                    f"Your {name} request ({request.start_date} to {request.end_date}, "
                    f"{request.total_days} day(s)) has been approved."
                ),
            )
        return (
            "SEND_LEAVE_REJECTED",
            f"Leave request update: {request.request_number}",
            (
                f"Your {name} request ({request.start_date} to {request.end_date}) was not "
                "approved. Contact your manager for details."
            ),
        )

