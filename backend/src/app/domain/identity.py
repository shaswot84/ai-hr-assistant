from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Person(Base):
    """Core human identity record shared by employees and candidates."""

    __tablename__ = "person"

    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(150), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationUser(Base):
    """Maps an authenticated identity to a Person and stores login credentials.

    The architecture doc models this table as a pure Keycloak-subject mapping
    with no coarse role or password (Keycloak owns both). The team dropped
    Keycloak in favor of self-issued JWT auth (no external IdP), so this table
    additionally stores ``coarse_role`` and ``password_hash`` as the local
    substitute source of truth for what Keycloak would otherwise have owned.
    ``identity_provider`` is kept at "local" so the shape still matches the
    doc's mapping pattern (``UNIQUE(identity_provider, external_subject)``)
    and stays extensible if a real IdP is reintroduced later.
    """

    __tablename__ = "application_user"
    __table_args__ = (UniqueConstraint("identity_provider", "external_subject"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"))
    identity_provider: Mapped[str] = mapped_column(String(50), default="local")
    external_subject: Mapped[str] = mapped_column(String(255), index=True)
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    coarse_role: Mapped[str] = mapped_column(String(30))  # HR_ADMIN | EMPLOYEE | CANDIDATE
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship()


class Department(Base):
    """Organizational department a vacancy or employee can belong to."""

    __tablename__ = "department"

    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Designation(Base):
    """A job title/level within a department, assigned to employees."""

    __tablename__ = "designation"
    __table_args__ = (UniqueConstraint("department_id", "title"),)

    designation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("department.department_id"))
    title: Mapped[str] = mapped_column(String(100))
    level: Mapped[int | None] = mapped_column(nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)


class Candidate(Base):
    """A person in the recruitment pipeline, not yet hired."""

    __tablename__ = "candidate"

    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"), unique=True)
    registration_date: Mapped[date] = mapped_column(Date)
    candidate_status: Mapped[str] = mapped_column(String(30), default="ACTIVE")
    hired_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee.employee_id"), nullable=True
    )
    hired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship()


class Employee(Base):
    """A hired person. Manager authority is derived from `manager_employee_id`."""

    __tablename__ = "employee"

    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"), unique=True)
    employee_code: Mapped[str] = mapped_column(String(30), unique=True)
    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("department.department_id"))
    designation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("designation.designation_id"))
    manager_employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee.employee_id"), nullable=True, index=True
    )
    joining_date: Mapped[date] = mapped_column(Date)
    employment_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    person: Mapped[Person] = relationship()


Index("ix_candidate_deleted_at", Candidate.deleted_at)
