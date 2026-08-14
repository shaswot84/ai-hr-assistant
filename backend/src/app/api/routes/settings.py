from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import require_role
from app.capabilities.settings import SettingsService
from app.contracts.auth import UserContext

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _svc() -> SettingsService:
    """FastAPI dependency that builds a SettingsService (reads/writes .env directly)."""
    return SettingsService()


class PromptIn(BaseModel):
    """Request body for setting a manager-editable prompt. Shared shape — every
    prompt setting (system or task/user template) round-trips as {prompt}."""

    prompt: str


class PromptOut(BaseModel):
    """Response carrying the active prompt plus whether it is the default. Shared
    shape across every prompt setting endpoint below."""

    prompt: str
    is_default: bool


def _prompt_routes(path: str, *, get, set_, reset) -> None:
    """Register the GET/PUT/POST-reset trio for one manager-editable prompt.

    All five prompt settings (resume-review system/user, resume-structuring
    system/user, keyword-suggestion system) share the exact same three-route
    shape — registered here once instead of five times to keep this file
    from being 90% copy-paste.
    """

    @router.get(f"/{path}", response_model=PromptOut, name=f"get_{path}")
    def _get(
        user: UserContext = Depends(require_role("HR_ADMIN")), svc: SettingsService = Depends(_svc)
    ):
        return PromptOut(**get(svc))

    @router.put(f"/{path}", response_model=PromptOut, name=f"put_{path}")
    def _put(
        body: PromptIn,
        user: UserContext = Depends(require_role("HR_ADMIN")),
        svc: SettingsService = Depends(_svc),
    ):
        return PromptOut(**set_(svc, body.prompt))

    @router.post(f"/{path}/reset", response_model=PromptOut, name=f"reset_{path}")
    def _reset(
        user: UserContext = Depends(require_role("HR_ADMIN")), svc: SettingsService = Depends(_svc)
    ):
        return PromptOut(**reset(svc))


_prompt_routes(
    "resume-review-prompt",
    get=lambda svc: svc.get_resume_review_prompt(),
    set_=lambda svc, prompt: svc.set_resume_review_prompt(prompt),
    reset=lambda svc: svc.reset_resume_review_prompt(),
)
_prompt_routes(
    "resume-review-user-prompt",
    get=lambda svc: svc.get_resume_review_user_prompt(),
    set_=lambda svc, prompt: svc.set_resume_review_user_prompt(prompt),
    reset=lambda svc: svc.reset_resume_review_user_prompt(),
)
_prompt_routes(
    "resume-structuring-system-prompt",
    get=lambda svc: svc.get_structuring_system_prompt(),
    set_=lambda svc, prompt: svc.set_structuring_system_prompt(prompt),
    reset=lambda svc: svc.reset_structuring_system_prompt(),
)
_prompt_routes(
    "resume-structuring-user-prompt",
    get=lambda svc: svc.get_structuring_user_prompt(),
    set_=lambda svc, prompt: svc.set_structuring_user_prompt(prompt),
    reset=lambda svc: svc.reset_structuring_user_prompt(),
)
_prompt_routes(
    "keyword-suggestion-prompt",
    get=lambda svc: svc.get_keyword_suggestion_prompt(),
    set_=lambda svc, prompt: svc.set_keyword_suggestion_prompt(prompt),
    reset=lambda svc: svc.reset_keyword_suggestion_prompt(),
)


class LlmConfigIn(BaseModel):
    """Request body for setting the LLM connection (API route, model, key).

    The form always shows the real current key (see LlmConfigOut), so this
    is the manager's actual intent, not a write-only diff — an empty
    api_key here means "no key configured", not "leave it unchanged".
    """

    api_base: str
    model: str
    api_key: str = ""


class LlmConfigOut(BaseModel):
    """Response carrying the active LLM connection settings, including the real API key.

    Shown as-is on the manager-only Settings page (behind a show/hide
    toggle in the UI) — it's the same key the manager themselves entered.
    """

    api_base: str
    model: str
    api_key: str
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
    return LlmConfigOut(
        **svc.set_llm_config(api_base=body.api_base, model=body.model, api_key=body.api_key)
    )


@router.post("/llm-config/reset", response_model=LlmConfigOut)
def reset_llm_config(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: SettingsService = Depends(_svc),
):
    """Clear all LLM connection overrides, restoring the .env-configured defaults (manager-only)."""
    return LlmConfigOut(**svc.reset_llm_config())
