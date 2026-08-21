from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import extract, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.identity import Employee
from app.domain.leave import CompanyHoliday, LeaveBalance, LeaveRequest, LeaveType


class LeaveTypeRepo:
    """Data access for leave type rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, leave_type: LeaveType) -> LeaveType:
        """Persist a new leave type and flush to obtain its generated id."""
        self._db.add(leave_type)
        await self._db.flush()
        return leave_type

    async def get(self, leave_type_id: uuid.UUID) -> LeaveType | None:
        """Fetch a leave type by id, or None if it does not exist."""
        return await self._db.get(LeaveType, leave_type_id)

    async def get_by_name_ci(self, name: str) -> LeaveType | None:
        """Fetch a leave type by name, case-insensitively.

        Used at create time to prevent `Annual` vs `annual` duplicates.
        """
        stmt = select(LeaveType).where(func.lower(LeaveType.leave_name) == name.strip().lower())
        return await self._db.scalar(stmt)

    async def list_active(self) -> list[LeaveType]:
        """List active leave types, ordered alphabetically."""
        stmt = (
            select(LeaveType)
            .where(LeaveType.status == "ACTIVE")
            .order_by(LeaveType.leave_name.asc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_all(self) -> list[LeaveType]:
        """List every leave type (including archived ones), ordered alphabetically."""
        stmt = select(LeaveType).order_by(LeaveType.leave_name.asc())
        res = await self._db.scalars(stmt)
        return list(res)


class LeaveBalanceRepo:
    """Data access for leave balance rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def get(
        self, employee_id: uuid.UUID, leave_type_id: uuid.UUID, year: int
    ) -> LeaveBalance | None:
        """Fetch an employee's balance for a specific leave type and year, or None."""
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
        return await self._db.scalar(stmt)

    async def list_for_employee(
        self, employee_id: uuid.UUID, year: int
    ) -> list[LeaveBalance]:
        """List all balance rows for one employee in one year."""
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.year == year,
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def create(self, balance: LeaveBalance) -> LeaveBalance:
        """Persist a new balance row and flush."""
        self._db.add(balance)
        await self._db.flush()
        return balance

    async def save(self, balance: LeaveBalance) -> None:
        """Flush pending changes to an existing balance row."""
        await self._db.flush()


class LeaveRequestRepo:
    """Data access for leave request rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, request: LeaveRequest) -> LeaveRequest:
        """Persist a new leave request and flush to obtain its generated id."""
        self._db.add(request)
        await self._db.flush()
        return request

    async def get(self, leave_request_id: uuid.UUID) -> LeaveRequest | None:
        """Fetch a leave request by id, or None if it does not exist (or was deleted)."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.leave_request_id == leave_request_id,
            LeaveRequest.deleted_at.is_(None),
        )
        return await self._db.scalar(stmt)

    async def get_by_request_number(self, request_number: str) -> LeaveRequest | None:
        """Fetch a leave request by its LR-YYYY-XXX reference, or None."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.request_number == request_number,
            LeaveRequest.deleted_at.is_(None),
        )
        return await self._db.scalar(stmt)

    async def get_for_employee(
        self, leave_request_id: uuid.UUID, employee_id: uuid.UUID
    ) -> LeaveRequest | None:
        """Fetch a leave request by id but only if it belongs to the given employee."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.leave_request_id == leave_request_id,
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.deleted_at.is_(None),
        )
        return await self._db.scalar(stmt)

    async def list_all(self) -> list[LeaveRequest]:
        """List every leave request across all employees, most recently submitted first."""
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.deleted_at.is_(None))
            .order_by(LeaveRequest.submitted_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_for_employee(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        """List an employee's own leave requests, most recently submitted first."""
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id, LeaveRequest.deleted_at.is_(None))
            .order_by(LeaveRequest.submitted_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_team_out_of_office(
        self,
        department_id: uuid.UUID | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> list[LeaveRequest]:
        """List approved and pending leave requests intersecting the date window."""
        stmt = (
            select(LeaveRequest)
            .join(Employee, LeaveRequest.employee_id == Employee.employee_id)
            .where(
                LeaveRequest.deleted_at.is_(None),
                LeaveRequest.status.in_(["APPROVED", "PENDING"]),
            )
        )
        if department_id is not None:
            stmt = stmt.where(Employee.department_id == department_id)
        if start_date is not None:
            stmt = stmt.where(LeaveRequest.end_date >= start_date)
        if end_date is not None:
            stmt = stmt.where(LeaveRequest.start_date <= end_date)
        stmt = stmt.order_by(LeaveRequest.start_date.asc())
        res = await self._db.scalars(stmt)
        return list(res)

    async def count_for_year(self, year: int) -> int:
        """Count leave requests submitted in a given year, across all employees."""
        count_stmt = select(func.count()).select_from(
            select(LeaveRequest)
            .where(LeaveRequest.request_number.like(f"LR-{year}-%"))
            .subquery()
        )
        return (await self._db.scalar(count_stmt)) or 0

    async def save(self, request: LeaveRequest) -> None:
        """Flush pending changes to an existing leave request row."""
        await self._db.flush()


class CompanyHolidayRepo:
    """Data access for company holiday rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, holiday: CompanyHoliday) -> CompanyHoliday:
        """Persist a new company holiday and flush."""
        self._db.add(holiday)
        await self._db.flush()
        return holiday

    async def get(self, holiday_id: uuid.UUID) -> CompanyHoliday | None:
        """Fetch a holiday by ID."""
        return await self._db.get(CompanyHoliday, holiday_id)

    async def get_by_date(self, holiday_date: date) -> CompanyHoliday | None:
        """Fetch a holiday by exact calendar date."""
        stmt = select(CompanyHoliday).where(CompanyHoliday.holiday_date == holiday_date)
        return await self._db.scalar(stmt)

    async def list_all(self, year: int | None = None) -> list[CompanyHoliday]:
        """List holidays, optionally filtering for a given year."""
        stmt = select(CompanyHoliday).order_by(CompanyHoliday.holiday_date.asc())
        if year is not None:
            stmt = select(CompanyHoliday).where(
                or_(
                    extract("year", CompanyHoliday.holiday_date) == year,
                    CompanyHoliday.is_recurring_yearly.is_(True),
                )
            ).order_by(CompanyHoliday.holiday_date.asc())
        res = await self._db.scalars(stmt)
        return list(res)

    async def delete(self, holiday: CompanyHoliday) -> None:
        """Delete a company holiday row."""
        await self._db.delete(holiday)
        await self._db.flush()

