from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class LeaveType(Base):
    """A category of leave (Annual, Sick, ...) managers configure once, reused every year."""

    __tablename__ = "leave_type"

    leave_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    leave_name: Mapped[str] = mapped_column(String(50), unique=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    default_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    is_paid: Mapped[bool] = mapped_column(Boolean)
    max_consecutive_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")  # ACTIVE | ARCHIVED


class LeaveBalance(Base):
    """An employee's allocated/used days for one leave type in one calendar year.

    `remaining_days` is deliberately not a column — it's derived
    (allocated - used) wherever it's needed, so there is never a second,
    driftable copy of the same fact.
    """

    __tablename__ = "leave_balance"
    __table_args__ = (UniqueConstraint("employee_id", "leave_type_id", "year"),)

    leave_balance_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employee.employee_id"))
    leave_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leave_type.leave_type_id"))
    year: Mapped[int] = mapped_column(Integer)
    allocated_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    used_days: Mapped[Decimal] = mapped_column(Numeric(5, 1), default=Decimal(0))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompanyHoliday(Base):
    """An official company holiday or office closure date.

    Deducted from leave requests so employees are only charged for working days.
    """

    __tablename__ = "company_holiday"

    holiday_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100))
    holiday_date: Mapped[date] = mapped_column(Date, unique=True, index=True)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_recurring_yearly: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class LeaveRequest(Base):
    """An employee's request to take leave, tracked through a single-decision lifecycle.

    Status is authoritative directly on this row (PENDING -> APPROVED |
    REJECTED, or PENDING -> CANCELLED by the requester) — no separate
    generic `approval` table, matching how `application.application_status`
    already works for recruitment rather than introducing a second pattern
    for the same kind of decision.
    """

    __tablename__ = "leave_request"

    leave_request_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(20), unique=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("employee.employee_id"))
    leave_type_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leave_type.leave_type_id"))
    start_date: Mapped[date] = mapped_column(Date)
    end_date: Mapped[date] = mapped_column(Date)
    total_days: Mapped[Decimal] = mapped_column(Numeric(5, 1))
    is_half_day: Mapped[bool] = mapped_column(Boolean, default=False)
    half_day_period: Mapped[str | None] = mapped_column(String(20), nullable=True)  # MORNING | AFTERNOON
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # PENDING | APPROVED | REJECTED | CANCELLED — terminal once decided or
    # cancelled, mirroring recruitment's DECIDABLE_STATUSES pattern.
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    decided_by_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee.employee_id"), nullable=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_leave_balance_employee", LeaveBalance.employee_id)
Index("ix_leave_request_employee_status", LeaveRequest.employee_id, LeaveRequest.status)
Index("ix_leave_request_deleted_at", LeaveRequest.deleted_at)
