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


class ScoreFactor(BaseModel):
    """One dimension the score was based on (e.g. "Skills Match": 85, "reason...")."""

    factor: str
    score: int = 0
    note: str = ""


class EvaluationDetail(BaseModel):
    """The structured ATS-style screening result: does this resume match the job, and why.

    This is a hiring-manager tool, not a resume-writing coach — there is
    deliberately no resume-quality feedback (clarity/formatting/rewrites)
    here, only whether and why the candidate matches this specific role.
    """

    match_score: int = 0
    recommendation: str = ""
    summary: str = ""
    score_factors: list[ScoreFactor] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []


class EvaluationOut(BaseModel):
    """API representation of an AI screening result (manager-only — never sent to candidates).

    ``score``/``overview`` are the compact headline fields; ``detail`` carries
    the full structured screening (score factors, strengths/weaknesses,
    keyword match) rendered on the manager's application review page.
    """

    score: int
    overview: str
    model: str | None
    evaluated_at: datetime
    detail: EvaluationDetail | None = None


class ApplicationOut(BaseModel):
    """Manager-facing representation of a job application, with its AI screening result."""

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


class ApplicationStatusOut(BaseModel):
    """Candidate-facing representation of their own application — status only.

    Deliberately excludes the AI screening result: candidates see whether
    they were shortlisted, not the scoring/strengths/weaknesses a manager
    uses to decide.
    """

    application_id: uuid.UUID
    vacancy_id: uuid.UUID
    vacancy_title: str | None = None
    application_status: str
    applied_at: datetime


class DecisionRequest(BaseModel):
    """Request payload for a manager's application decision."""

    action: str  # "approve" | "reject"
