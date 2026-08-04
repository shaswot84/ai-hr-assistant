from __future__ import annotations

import uuid
from datetime import date, datetime

from pydantic import BaseModel, Field


class VacancyCreate(BaseModel):
    """Request payload for creating a vacancy."""

    title: str = Field(min_length=1, max_length=150)
    department_name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    employment_type: str = Field(min_length=1, max_length=30)
    opening_date: date | None = None
    closing_date: date | None = None


class VacancyOut(BaseModel):
    """API representation of a vacancy."""

    vacancy_id: uuid.UUID
    title: str
    department_name: str | None = None
    description: str | None
    employment_type: str
    opening_date: date | None
    closing_date: date | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EvaluationOut(BaseModel):
    """API representation of an AI resume evaluation."""

    score: int
    overview: str
    model: str | None
    evaluated_at: datetime


class ApplicationOut(BaseModel):
    """API representation of a job application (with optional evaluation)."""

    application_id: uuid.UUID
    vacancy_id: uuid.UUID
    vacancy_title: str | None = None
    application_status: str
    applied_at: datetime
    evaluated: bool = False
    evaluation: EvaluationOut | None = None


class ApplicationDetailOut(ApplicationOut):
    """Application response extended with candidate contact details (manager view)."""

    candidate_name: str | None = None
    candidate_email: str | None = None


class DecisionRequest(BaseModel):
    """Request payload for a manager's application decision."""

    action: str  # "approve" | "reject"
