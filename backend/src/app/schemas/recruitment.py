from __future__ import annotations

import uuid
from datetime import date, datetime
from pydantic import BaseModel, Field
from pydantic.alias_generators import to_camel


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
    """API representation of a rich AI resume evaluation.

    ``score``/``overview`` are the compact headline fields; ``detail`` carries
    the full verbose review (sections, bullets, keyword matches) rendered by the
    manager and candidate portals.
    """

    score: int
    overview: str
    model: str | None
    evaluated_at: datetime
    detail: "EvaluationDetail | None" = None


class FeedbackSection(BaseModel):
    """A named feedback dimension (clarity/impact/formatting) with a summary + issues."""

    summary: str = ""
    issues: list[str] = []


class ImprovedBullet(BaseModel):
    """A before/after resume bullet rewrite produced by the evaluator."""

    original: str
    improved: str
    reason: str = ""


class JobMatch(BaseModel):
    """How well the resume matches the target job (jobMatch)."""

    model_config = {"alias_generator": to_camel, "populate_by_name": True}

    match_score: int = 0
    summary: str = ""
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []


class EvaluationDetail(BaseModel):
    """The full structured review returned to rich evaluation UIs."""

    overall_score: int = 0
    score_justification: str = ""
    clarity: FeedbackSection = FeedbackSection()
    impact: FeedbackSection = FeedbackSection()
    formatting: FeedbackSection = FeedbackSection()
    missing_sections: list[str] = []
    improved_bullets: list[ImprovedBullet] = []
    job_match: JobMatch | None = None


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
