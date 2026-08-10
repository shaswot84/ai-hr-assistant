"""Pydantic DTOs for the People (org directory) API.

Mirrors `schemas/recruitment.py`: request payloads are explicit `*Create`
models, responses are `*Out` models. Employee/designation responses pull
display names from several rows (Person/Department/Designation/manager), so
those are assembled explicitly in the route layer rather than via
`from_attributes`; simple rows (departments) use `from_attributes` directly.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, EmailStr, Field


class DepartmentCreate(BaseModel):
    """Request payload for creating a department."""

    name: str = Field(min_length=1, max_length=100)


class DepartmentOut(BaseModel):
    """API representation of a department."""

    department_id: uuid.UUID
    name: str

    model_config = {"from_attributes": True}


class DesignationCreate(BaseModel):
    """Request payload for creating a designation within a department."""

    department_id: uuid.UUID
    title: str = Field(min_length=1, max_length=100)
    level: int | None = Field(default=None, ge=1)


class DesignationOut(BaseModel):
    """API representation of a designation (job title/level in a department)."""

    designation_id: uuid.UUID
    department_id: uuid.UUID
    department_name: str | None = None
    title: str
    level: int | None
    is_active: bool

    model_config = {"from_attributes": True}


class EmployeeCreate(BaseModel):
    """Request payload for ad-hoc employee creation.

    HR provides the login credentials (`password`); the API provisions the
    Person + ApplicationUser (EMPLOYEE role) + Employee rows atomically.
    """

    first_name: str = Field(min_length=1, max_length=100)
    last_name: str = Field(min_length=1, max_length=100)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=20)
    employee_code: str = Field(min_length=1, max_length=30)
    department_id: uuid.UUID
    designation_id: uuid.UUID
    manager_employee_id: uuid.UUID | None = None
    joining_date: date
    password: str = Field(min_length=8, max_length=128)


class EmployeeUpdate(BaseModel):
    """Request payload for updating an existing employee (all fields optional).

    Only the fields the client actually sends are applied (patch semantics);
    `manager_employee_id` may be explicitly `null` to clear the manager link.
    """

    first_name: str | None = Field(default=None, min_length=1, max_length=100)
    last_name: str | None = Field(default=None, min_length=1, max_length=100)
    phone: str | None = Field(default=None, max_length=20)
    department_id: uuid.UUID | None = None
    designation_id: uuid.UUID | None = None
    manager_employee_id: uuid.UUID | None = None
    joining_date: date | None = None
    employment_status: str | None = Field(default=None, max_length=20)


class HireCandidateRequest(BaseModel):
    """Request payload for hiring a shortlisted candidate from their application."""

    employee_code: str = Field(min_length=1, max_length=30)
    department_id: uuid.UUID
    designation_id: uuid.UUID
    manager_employee_id: uuid.UUID | None = None
    joining_date: date


class EmployeeOut(BaseModel):
    """API representation of an employee (directory row + resolved display names)."""

    employee_id: uuid.UUID
    employee_code: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    department_id: uuid.UUID
    department_name: str | None = None
    designation_id: uuid.UUID
    designation_title: str | None = None
    manager_employee_id: uuid.UUID | None
    manager_name: str | None = None
    joining_date: date
    employment_status: str
    created_at: datetime
    updated_at: datetime
