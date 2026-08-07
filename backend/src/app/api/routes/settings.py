from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_role
from app.capabilities.settings import SettingsService
from app.contracts.auth import UserContext
from app.db.sync_session import get_db

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _svc(db=Depends(get_db)) -> SettingsService:
    """FastAPI dependency that builds a SettingsService bound to the request's DB session."""
    return SettingsService(db)


class ResumeReviewPromptIn(BaseModel):
    """Request body for setting the resume-review system prompt."""

    prompt: str


class ResumeReviewPromptOut(BaseModel):
    """Response carrying the active prompt plus whether it is the default."""

    prompt: str
    is_default: bool


@router.get("/resume-review-prompt", response_model=ResumeReviewPromptOut)
def get_resume_review_prompt(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Return the active resume-review system prompt and whether it is the default (manager-only)."""
    return ResumeReviewPromptOut(**svc.get_resume_review_prompt())


@router.put("/resume-review-prompt", response_model=ResumeReviewPromptOut)
def put_resume_review_prompt(
    body: ResumeReviewPromptIn,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Persist a manager-provided resume-review system prompt (manager-only)."""
    return ResumeReviewPromptOut(**svc.set_resume_review_prompt(body.prompt))


@router.post("/resume-review-prompt/reset", response_model=ResumeReviewPromptOut)
def reset_resume_review_prompt(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Clear any customised resume-review prompt, restoring the default (manager-only)."""
    return ResumeReviewPromptOut(**svc.reset_resume_review_prompt())


class LlmConfigIn(BaseModel):
    """Request body for setting the LLM connection (API route, model, key)."""

    api_base: str
    model: str
    api_key: str | None = None  # write-only; blank/omitted leaves the stored key unchanged


class LlmConfigOut(BaseModel):
    """Response carrying the active LLM connection settings — never the raw API key."""

    api_base: str
    model: str
    api_key_set: bool
    is_default: bool


@router.get("/llm-config", response_model=LlmConfigOut)
def get_llm_config(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Return the active LLM connection settings (manager-only)."""
    return LlmConfigOut(**svc.get_llm_config())


@router.put("/llm-config", response_model=LlmConfigOut)
def put_llm_config(
    body: LlmConfigIn,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Persist manager-provided LLM route/model/key settings (manager-only)."""
    return LlmConfigOut(**svc.set_llm_config(api_base=body.api_base, model=body.model, api_key=body.api_key))


@router.post("/llm-config/reset", response_model=LlmConfigOut)
def reset_llm_config(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Clear all LLM connection overrides, restoring the .env-configured defaults (manager-only)."""
    return LlmConfigOut(**svc.reset_llm_config())
