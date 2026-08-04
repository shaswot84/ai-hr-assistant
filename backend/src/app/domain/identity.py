from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Date, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Person(Base):
    """Core human identity record shared by employees and candidates."""

    __tablename__ = "person"

    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    first_name: Mapped[str] = mapped_column(String(100))
    last_name: Mapped[str] = mapped_column(String(100))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)


class ApplicationUser(Base):
    """Maps an external auth subject (Keycloak sub / dev-stub id) to a Person."""

    __tablename__ = "application_user"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    external_subject: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"))
    coarse_role: Mapped[str] = mapped_column(String(30))

    person: Mapped[Person] = relationship()


class Department(Base):
    """Organizational department a vacancy can belong to."""

    __tablename__ = "department"

    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(100), unique=True)


class Candidate(Base):
    """A person in the recruitment pipeline, not yet hired."""

    __tablename__ = "candidate"

    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"), unique=True)
    registration_date: Mapped[date] = mapped_column(Date)


class Employee(Base):
    """A hired person with an employee number (manager authority is derived elsewhere)."""

    __tablename__ = "employee"

    employee_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    person_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("person.person_id"), unique=True)
    employee_number: Mapped[str] = mapped_column(String(30), unique=True)

    person: Mapped[Person] = relationship()