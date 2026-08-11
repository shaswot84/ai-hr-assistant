from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class LeaveTypeCreate(BaseModel):
    """Request payload for creating a leave type."""

    leave_name: str = Field(min_length=1, max_length=50)
    description: str | None = None
    default_days: Decimal = Field(gt=0)
    requires_approval: bool = True
    is_paid: bool = True
    max_consecutive_days: int | None = Field(default=None, gt=0)


class LeaveTypeOut(BaseModel):
    """API representation of a leave type."""

    leave_type_id: uuid.UUID
    leave_name: str
    description: str | None
    default_days: Decimal
    requires_approval: bool
    is_paid: bool
    max_consecutive_days: int | None
    status: str

    model_config = {"from_attributes": True}


class LeaveBalanceOut(BaseModel):
    """An employee's allocated/used/remaining days for one leave type in one year."""

    leave_type_id: uuid.UUID
    leave_type_name: str
    year: int
    allocated_days: Decimal
    used_days: Decimal
    remaining_days: Decimal


class LeaveRequestCreate(BaseModel):
    """Request payload for submitting a leave request."""

    leave_type_id: uuid.UUID
    start_date: date
    end_date: date
    reason: str | None = Field(default=None, max_length=500)


class LeaveRequestOut(BaseModel):
    """Employee-facing representation of a leave request (their own)."""

    leave_request_id: uuid.UUID
    request_number: str
    leave_type_id: uuid.UUID
    leave_type_name: str
    start_date: date
    end_date: date
    total_days: Decimal
    reason: str | None
    status: str
    submitted_at: datetime
    decided_at: datetime | None


class LeaveRequestDetailOut(LeaveRequestOut):
    """Manager-facing leave request, extended with whose request it is."""

    employee_name: str | None = None
    employee_email: str | None = None


class LeaveDecisionRequest(BaseModel):
    """Request payload for a manager's leave decision."""

    action: str  # "approve" | "reject"
