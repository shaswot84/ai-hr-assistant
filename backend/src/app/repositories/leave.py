from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.leave import LeaveBalance, LeaveRequest, LeaveType


class LeaveTypeRepo:
    """Data access for leave type rows."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def create(self, leave_type: LeaveType) -> LeaveType:
        """Persist a new leave type and flush to obtain its generated id."""
        self._db.add(leave_type)
        self._db.flush()
        return leave_type

    def get(self, leave_type_id: uuid.UUID) -> LeaveType | None:
        """Fetch a leave type by id, or None if it does not exist."""
        return self._db.get(LeaveType, leave_type_id)

    def get_by_name(self, leave_name: str) -> LeaveType | None:
        """Fetch a leave type by its unique name, or None if it does not exist."""
        stmt = select(LeaveType).where(LeaveType.leave_name == leave_name)
        return self._db.scalar(stmt)

    def list_active(self) -> list[LeaveType]:
        """List active leave types, alphabetically."""
        stmt = (
            select(LeaveType)
            .where(LeaveType.status == "ACTIVE")
            .order_by(LeaveType.leave_name)
        )
        return list(self._db.scalars(stmt))

    def list_all(self) -> list[LeaveType]:
        """List every leave type (active and archived), alphabetically."""
        stmt = select(LeaveType).order_by(LeaveType.leave_name)
        return list(self._db.scalars(stmt))


class LeaveBalanceRepo:
    """Data access for per-employee, per-year leave balance rows."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def get(
        self, employee_id: uuid.UUID, leave_type_id: uuid.UUID, year: int
    ) -> LeaveBalance | None:
        """Fetch one balance row, or None if the employee has none for that type/year."""
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id,
            LeaveBalance.leave_type_id == leave_type_id,
            LeaveBalance.year == year,
        )
        return self._db.scalar(stmt)

    def list_for_employee(self, employee_id: uuid.UUID, year: int) -> list[LeaveBalance]:
        """List an employee's balances for every leave type in a given year."""
        stmt = select(LeaveBalance).where(
            LeaveBalance.employee_id == employee_id, LeaveBalance.year == year
        )
        return list(self._db.scalars(stmt))

    def create(self, balance: LeaveBalance) -> LeaveBalance:
        """Persist a new balance row and flush to obtain its generated id."""
        self._db.add(balance)
        self._db.flush()
        return balance

    def save(self, balance: LeaveBalance) -> None:
        """Flush pending changes to an existing balance row."""
        self._db.flush()


class LeaveRequestRepo:
    """Data access for leave request rows."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def create(self, request: LeaveRequest) -> LeaveRequest:
        """Persist a new leave request and flush to obtain its generated id."""
        self._db.add(request)
        self._db.flush()
        return request

    def get(self, leave_request_id: uuid.UUID) -> LeaveRequest | None:
        """Fetch a leave request by id, or None if it does not exist (or was deleted)."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.leave_request_id == leave_request_id,
            LeaveRequest.deleted_at.is_(None),
        )
        return self._db.scalar(stmt)

    def get_for_employee(
        self, leave_request_id: uuid.UUID, employee_id: uuid.UUID
    ) -> LeaveRequest | None:
        """Fetch a leave request by id but only if it belongs to the given employee."""
        stmt = select(LeaveRequest).where(
            LeaveRequest.leave_request_id == leave_request_id,
            LeaveRequest.employee_id == employee_id,
            LeaveRequest.deleted_at.is_(None),
        )
        return self._db.scalar(stmt)

    def list_all(self) -> list[LeaveRequest]:
        """List every leave request across all employees, most recently submitted first."""
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.deleted_at.is_(None))
            .order_by(LeaveRequest.submitted_at.desc())
        )
        return list(self._db.scalars(stmt))

    def list_for_employee(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        """List an employee's own leave requests, most recently submitted first."""
        stmt = (
            select(LeaveRequest)
            .where(LeaveRequest.employee_id == employee_id, LeaveRequest.deleted_at.is_(None))
            .order_by(LeaveRequest.submitted_at.desc())
        )
        return list(self._db.scalars(stmt))

    def count_for_year(self, year: int) -> int:
        """Count leave requests submitted in a given year, across all employees.

        Used to generate the next sequence number for `request_number`
        (`LR-YYYY-XXX`) — a simple global-per-year counter, not scoped to
        one employee or leave type.
        """
        stmt = select(LeaveRequest).where(
            LeaveRequest.request_number.like(f"LR-{year}-%")
        )
        return len(list(self._db.scalars(stmt)))

    def save(self, request: LeaveRequest) -> None:
        """Flush pending changes to an existing leave request row."""
        self._db.flush()
