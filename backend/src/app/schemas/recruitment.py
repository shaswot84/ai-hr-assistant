from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field


class ScoringKeyword(BaseModel):
    """One keyword a vacancy is scored against, with its importance tier.

    The tier alone determines weight at scoring time (fixed tier -> weight
    mapping in evaluation.keyword_suggestion.TIER_WEIGHTS) — no raw weight
    is stored here, so the tier ratio can change later without a data
    migration.
    """

    keyword: str = Field(min_length=1, max_length=100)
    tier: Literal["critical", "important", "nice_to_have"]


class KeywordSuggestionRequest(BaseModel):
    """Request payload for generating candidate scoring keywords from a job posting."""

    title: str = Field(min_length=1, max_length=150)
    description: str = Field(default="", max_length=10000)


class KeywordSuggestionOut(BaseModel):
    """LLM-suggested keywords for a manager to review, check/uncheck, and re-tier."""

    keywords: list[ScoringKeyword]


class VacancyCreate(BaseModel):
    """Request payload for creating a vacancy.

    `scoring_keywords` is required (at least one) — every vacancy needs a
    real, explainable scoring rubric before candidates can be ranked
    against it; there's no "post now, add keywords later" path.
    """

    title: str = Field(min_length=1, max_length=150)
    department_name: str = Field(min_length=1, max_length=100)
    description: str | None = None
    employment_type: str = Field(min_length=1, max_length=30)
    opening_date: date | None = None
    closing_date: date | None = None
    scoring_keywords: list[ScoringKeyword] = Field(min_length=1)


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
    scoring_keywords: list[ScoringKeyword] = []
    created_at: datetime

    model_config = {"from_attributes": True}


class KeyFactor(BaseModel):
    """One qualitative dimension behind the recommendation (e.g. "Skills Match": "reason...").

    Deliberately has no numeric score — an LLM asked for "a number" with no
    rubric produces digits that look precise but aren't comparable across
    candidates; the note is the actual, groundable signal.
    """

    factor: str
    note: str = ""


class Requirement(BaseModel):
    """One explicit must-have from the job description, checked against the resume.

    Distinct from `score_factors` — this is a hard pass/fail gate, not a
    soft ranking dimension. `met` for a years-of-experience requirement is
    computed deterministically from extracted work-history dates rather
    than left to the model's own arithmetic.
    """

    requirement: str
    met: bool = False
    evidence: str = ""


class WorkExperienceOut(BaseModel):
    """One work-history entry pulled from the resume, dates kept as written.

    `start_year`/`end_year` are the same parsed values the years-of-experience
    math is computed from (see `evaluation.resume_structuring`) — None means
    that date string didn't contain a recognizable year (e.g. a garbled
    extraction), so a UI shouldn't display the raw string as if it were
    reliable, the way it would for a date that parsed cleanly.
    """

    title: str = ""
    company: str = ""
    start_date: str = ""
    end_date: str = ""
    start_year: int | None = None
    end_year: int | None = None
    is_current: bool = False


class EducationOut(BaseModel):
    degree: str = ""
    institution: str = ""
    graduation_year: int | None = None


class StructuredResumeOut(BaseModel):
    """Structured facts extracted from the resume, separate from the job-fit score.

    `total_years_experience` is always computed deterministically from the
    parsed work-history dates (see `evaluation.resume_structuring`), never
    the model's own arithmetic — shown here so a manager can see the actual
    basis for the "Experience Level" factor and any years-based requirement.
    """

    work_experience: list[WorkExperienceOut] = []
    education: list[EducationOut] = []
    skills: list[str] = []
    total_years_experience: float = 0.0


class CandidateProfile(BaseModel):
    """Identity/contact info the AI extracted directly from the resume text.

    Distinct from the candidate's account (person.email etc.) — a resume
    often has more complete or more current contact info than the account
    it was uploaded from, and cross-checking the two is useful to a
    hiring manager. Every field is best-effort and may be empty.
    """

    name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""
    headline: str = ""  # e.g. "Senior Backend Engineer, 7 years experience"


class KeywordMatch(BaseModel):
    """Whether one of the vacancy's configured scoring keywords was found in the resume.

    The tier (and its weight) lives on the vacancy's `scoring_keywords`, not
    here — this is purely the per-resume presence judgment `keyword_score`
    is computed from.
    """

    keyword: str
    present: bool = False
    evidence: str = ""


class EvaluationDetail(BaseModel):
    """The structured ATS-style screening result: does this resume match the job, and why.

    This is a hiring-manager tool, not a resume-writing coach — there is
    deliberately no resume-quality feedback (clarity/formatting/rewrites)
    here, only whether and why the candidate matches this specific role.
    """

    requirements: list[Requirement] = []
    requirements_met: bool = True
    recommendation: str = ""
    summary: str = ""
    key_factors: list[KeyFactor] = []
    strengths: list[str] = []
    weaknesses: list[str] = []
    matched_keywords: list[str] = []
    missing_keywords: list[str] = []
    keyword_matches: list[KeywordMatch] = []
    candidate_profile: CandidateProfile | None = None
    structured_resume: StructuredResumeOut | None = None


class EvaluationOut(BaseModel):
    """API representation of an AI screening result (manager-only — never sent to candidates).

    ``overview`` is the compact headline field; ``detail`` carries the full
    structured screening (requirements, key factors, strengths/weaknesses,
    keyword match) rendered on the manager's application review page.
    ``failed`` marks a screening that couldn't run at all (AI provider
    unavailable) — the UI shows an error + retry action instead of treating
    it as a real result. ``keyword_score`` is 0-100, deterministically
    computed from the vacancy's weighted scoring keywords — None when the
    vacancy has none configured.
    """

    overview: str
    failed: bool = False
    keyword_score: int | None = None
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
    # True once the candidate was converted into an employee via the hire
    # handoff — the application status itself stays SHORTLISTED.
    hired: bool = False


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
