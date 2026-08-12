from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Vacancy(Base):
    """A job opening posted by a manager for candidates to apply to."""

    __tablename__ = "vacancy"

    vacancy_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(150))
    department_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("department.department_id"))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    employment_type: Mapped[str] = mapped_column(String(30))
    opening_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    closing_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by_employee_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("employee.employee_id")
    )
    approval_status: Mapped[str] = mapped_column(String(20), default="APPROVED")
    status: Mapped[str] = mapped_column(String(30), default="OPEN")  # DRAFT|OPEN|CLOSED
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Application(Base):
    """A candidate's application to a vacancy, tracking its life-cycle status."""

    __tablename__ = "application"
    __table_args__ = (UniqueConstraint("candidate_id", "vacancy_id"),)

    application_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    candidate_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("candidate.candidate_id"))
    vacancy_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("vacancy.vacancy_id"))
    cv_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # APPLIED | SHORTLISTED | REJECTED | WITHDRAWN — WITHDRAWN has no capability
    # method yet (no withdraw endpoint this week); the column/state exists so
    # the candidate-initiated withdraw flow can land later without a migration.
    application_status: Mapped[str] = mapped_column(String(30), default="APPLIED")
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    vacancy: Mapped[Vacancy] = relationship()
    evaluation: Mapped[ApplicationEvaluation | None] = relationship(back_populates="application")


class ApplicationEvaluation(Base):
    """Advisory AI output for an application. One application can have many (re-evaluations)."""

    __tablename__ = "application_evaluation"

    evaluation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    application_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("application.application_id"), index=True
    )
    overview: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    #: True when the screening couldn't run at all (AI provider unavailable)
    #: — distinct from a normal result, so the UI shows a clear error + a
    #: retry action instead of pretending there's a real assessment.
    failed: Mapped[bool] = mapped_column(Boolean, default=False)
    model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    application: Mapped[Application] = relationship(back_populates="evaluation")


Index("ix_application_candidate", Application.candidate_id)
Index("ix_application_vacancy_status", Application.vacancy_id, Application.application_status)
Index("ix_vacancy_deleted_at", Vacancy.deleted_at)
Index("ix_application_deleted_at", Application.deleted_at)
