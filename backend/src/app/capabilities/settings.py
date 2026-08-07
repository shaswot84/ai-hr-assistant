from __future__ import annotations

from app.config.settings import get_settings
from app.evaluation.scoring import DEFAULT_SYSTEM_PROMPT
from app.repositories.settings import SettingRepo

#: Key used to store a manager-overridden resume-review system prompt.
RESUME_REVIEW_PROMPT_KEY = "resume_review_system_prompt"

#: Keys used to store manager-overridden LLM connection settings. Stored
#: separately (not one JSON blob) so a partial override — e.g. just the
#: model — doesn't require re-submitting the others.
LLM_API_BASE_KEY = "llm_api_base"
LLM_MODEL_KEY = "llm_model"
LLM_API_KEY_KEY = "llm_api_key"


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

    # ---- LLM connection (API route / model / key) ---------------------

    def get_llm_config(self) -> dict[str, str | bool]:
        """Return the active LLM connection settings for display (never the raw API key)."""
        defaults = get_settings().chat
        stored_base = self._settings.get_value(LLM_API_BASE_KEY)
        stored_model = self._settings.get_value(LLM_MODEL_KEY)
        stored_key = self._settings.get_value(LLM_API_KEY_KEY)
        return {
            "api_base": stored_base or defaults.api_base,
            "model": stored_model or defaults.model,
            "api_key_set": bool(stored_key or defaults.api_key),
            "is_default": stored_base is None and stored_model is None and stored_key is None,
        }

    def set_llm_config(
        self, *, api_base: str, model: str, api_key: str | None
    ) -> dict[str, str | bool]:
        """Persist manager-provided LLM connection settings and commit.

        ``api_key`` is write-only: a blank/None value leaves any previously
        stored key untouched (so the manager never has to re-paste it just to
        change the model), matching how secret fields are normally edited.
        """
        self._settings.set_value(LLM_API_BASE_KEY, api_base.strip())
        self._settings.set_value(LLM_MODEL_KEY, model.strip())
        if api_key and api_key.strip():
            self._settings.set_value(LLM_API_KEY_KEY, api_key.strip())
        self._db.commit()
        return self.get_llm_config()

    def reset_llm_config(self) -> dict[str, str | bool]:
        """Clear all LLM connection overrides, restoring the .env-configured defaults."""
        self._settings.delete(LLM_API_BASE_KEY)
        self._settings.delete(LLM_MODEL_KEY)
        self._settings.delete(LLM_API_KEY_KEY)
        self._db.commit()
        return self.get_llm_config()

    def resolved_llm_overrides(self) -> dict[str, str | None]:
        """Return raw api_base/model/api_key overrides for the worker (None = use .env default)."""
        return {
            "api_base": self._settings.get_value(LLM_API_BASE_KEY),
            "model": self._settings.get_value(LLM_MODEL_KEY),
            "api_key": self._settings.get_value(LLM_API_KEY_KEY),
        }
