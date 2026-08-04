from __future__ import annotations

from app.evaluation.scoring import DEFAULT_SYSTEM_PROMPT
from app.repositories.settings import SettingRepo

#: Key used to store a manager-overridden resume-review system prompt.
RESUME_REVIEW_PROMPT_KEY = "resume_review_system_prompt"


class SettingsService:
    """Application configuration management (capability layer).

    Presently supports the manager-editable system prompt used when the LLM
    evaluates resumes. Values are stored authoritatively in PostgreSQL so the
    worker and API always share the same configuration.
    """

    def __init__(self, db) -> None:
        """Bind the service to a DB session."""
        self._db = db
        self._settings = SettingRepo(db)

    def get_resume_review_prompt(self) -> dict[str, str]:
        """Return the active resume-review system prompt plus a flag if it was customised."""
        stored = self._settings.get_value(RESUME_REVIEW_PROMPT_KEY)
        is_default = not stored or stored.strip() == DEFAULT_SYSTEM_PROMPT.strip()
        return {"prompt": (stored or DEFAULT_SYSTEM_PROMPT), "is_default": is_default}

    def set_resume_review_prompt(self, prompt: str) -> dict[str, str]:
        """Persist a manager-provided resume-review system prompt and commit."""
        normalized = prompt.strip() or DEFAULT_SYSTEM_PROMPT
        self._settings.set_value(RESUME_REVIEW_PROMPT_KEY, normalized)
        self._db.commit()
        return {"prompt": normalized, "is_default": normalized == DEFAULT_SYSTEM_PROMPT.strip()}

    def reset_resume_review_prompt(self) -> dict[str, str]:
        """Clear any customised prompt so the default is used, and commit."""
        self._settings.delete(RESUME_REVIEW_PROMPT_KEY)
        self._db.commit()
        return {"prompt": DEFAULT_SYSTEM_PROMPT, "is_default": True}

    def resolved_prompt(self) -> str:
        """Return the active system prompt for evaluation use (default if none overridden)."""
        return self._settings.get_value(RESUME_REVIEW_PROMPT_KEY) or DEFAULT_SYSTEM_PROMPT