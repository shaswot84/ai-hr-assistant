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
    is_half_day: bool = False
    half_day_period: str | None = Field(default=None, max_length=20)
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
    is_half_day: bool = False
    half_day_period: str | None = None
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


class CompanyHolidayCreate(BaseModel):
    """Request payload for creating an official company holiday."""

    name: str = Field(min_length=1, max_length=100)
    holiday_date: date
    description: str | None = Field(default=None, max_length=255)
    is_recurring_yearly: bool = False


class CompanyHolidayOut(BaseModel):
    """API representation of an official company holiday."""

    holiday_id: uuid.UUID
    name: str
    holiday_date: date
    description: str | None = None
    is_recurring_yearly: bool = False
    created_at: datetime

    model_config = {"from_attributes": True}


class WorkingDaysCalculationRequest(BaseModel):
    """Request payload to calculate working days for a proposed date range."""

    start_date: date
    end_date: date
    is_half_day: bool = False
    half_day_period: str | None = None


class WorkingDaysCalculationOut(BaseModel):
    """Working days calculation breakdown."""

    start_date: date
    end_date: date
    total_working_days: Decimal
    calendar_days: int
    weekend_days: int
    holiday_days: int
    holidays_in_range: list[CompanyHolidayOut]


class TeamMemberOutOfOfficeOut(BaseModel):
    """Team member out-of-office entry for team calendar."""

    leave_request_id: uuid.UUID
    employee_id: uuid.UUID
    employee_name: str
    department_id: uuid.UUID | None = None
    department_name: str | None = None
    leave_type_name: str
    start_date: date
    end_date: date
    total_days: Decimal
    is_half_day: bool = False
    half_day_period: str | None = None
    status: str


class EmployeeLeaveBalanceOut(BaseModel):
    """An employee's leave balance overview with identity context."""

    employee_name: str
    employee_code: str
    department_name: str | None = None
    year: int
    balances: list[LeaveBalanceOut]


class AllEmployeeBalancesOut(BaseModel):
    """All active employees' leave balances with organization hierarchy."""

    employee_id: uuid.UUID
    employee_code: str
    employee_name: str
    employee_email: str
    manager_employee_id: uuid.UUID | None = None
    department_name: str | None = None
    designation_title: str | None = None
    year: int
    balances: list[LeaveBalanceOut]


