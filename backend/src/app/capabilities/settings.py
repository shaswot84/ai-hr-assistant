from __future__ import annotations

from app.config.settings import ChatSettings
from app.evaluation.keyword_suggestion import (
    DEFAULT_SYSTEM_PROMPT as KEYWORD_SUGGESTION_DEFAULT_PROMPT,
)
from app.evaluation.scoring import DEFAULT_SYSTEM_PROMPT
from app.repositories.env_settings import EnvFileSettingRepo

#: The out-of-the-box defaults baked into the code (used as the fallback
#: when a key is absent from `.env` entirely, and as the baseline
#: `is_default` is measured against). Read from the pydantic field
#: definitions directly rather than `get_settings().chat` — that reflects
#: `.env` as it was at container boot, which is now the exact same file
#: this service reads/writes live, so comparing against it would be
#: circular (always "customized" the moment `.env` has any values at all).
_CHAT_DEFAULT_API_BASE = ChatSettings.model_fields["api_base"].default
_CHAT_DEFAULT_MODEL = ChatSettings.model_fields["model"].default
_CHAT_DEFAULT_API_KEY = ChatSettings.model_fields["api_key"].default

#: Key used to store a manager-overridden resume-review system prompt.
RESUME_REVIEW_PROMPT_KEY = "RESUME_REVIEW_SYSTEM_PROMPT"

#: Key used to store a manager-overridden keyword-suggestion system prompt
#: (the "Generate Weighted Keywords" step on vacancy creation).
KEYWORD_SUGGESTION_PROMPT_KEY = "KEYWORD_SUGGESTION_SYSTEM_PROMPT"

#: Keys used to store manager-overridden LLM connection settings — the same
#: names `ChatSettings` (config/settings.py, env_prefix `OLLAMA_CHAT_`) reads
#: as its own defaults, so `.env` has exactly one variable per setting
#: rather than a shadow copy under a different name.
LLM_API_BASE_KEY = "OLLAMA_CHAT_API_BASE"
LLM_MODEL_KEY = "OLLAMA_CHAT_MODEL"
LLM_API_KEY_KEY = "OLLAMA_CHAT_API_KEY"


class SettingsService:
    """Application configuration management (capability layer).

    Manager-editable settings (the resume-review system prompt, the LLM
    connection) are stored directly in `.env` via `EnvFileSettingRepo`,
    which re-reads the file on every call — so a change made through the
    API takes effect on the worker's very next job, no restart needed.
    """

    def __init__(self) -> None:
        self._settings = EnvFileSettingRepo()

    def get_resume_review_prompt(self) -> dict[str, str]:
        """Return the active resume-review system prompt plus a flag if it was customised."""
        stored = self._settings.get_value(RESUME_REVIEW_PROMPT_KEY)
        is_default = not stored or stored.strip() == DEFAULT_SYSTEM_PROMPT.strip()
        return {"prompt": (stored or DEFAULT_SYSTEM_PROMPT), "is_default": is_default}

    def set_resume_review_prompt(self, prompt: str) -> dict[str, str]:
        """Persist a manager-provided resume-review system prompt."""
        normalized = prompt.strip() or DEFAULT_SYSTEM_PROMPT
        self._settings.set_value(RESUME_REVIEW_PROMPT_KEY, normalized)
        return {"prompt": normalized, "is_default": normalized == DEFAULT_SYSTEM_PROMPT.strip()}

    def reset_resume_review_prompt(self) -> dict[str, str]:
        """Clear any customised prompt so the default is used."""
        self._settings.delete(RESUME_REVIEW_PROMPT_KEY)
        return {"prompt": DEFAULT_SYSTEM_PROMPT, "is_default": True}

    def resolved_prompt(self) -> str:
        """Return the active system prompt for evaluation use (default if none overridden)."""
        return self._settings.get_value(RESUME_REVIEW_PROMPT_KEY) or DEFAULT_SYSTEM_PROMPT

    # ---- keyword-suggestion system prompt ------------------------------

    def get_keyword_suggestion_prompt(self) -> dict[str, str]:
        """Return the active keyword-suggestion system prompt plus a flag if it was customised."""
        stored = self._settings.get_value(KEYWORD_SUGGESTION_PROMPT_KEY)
        is_default = not stored or stored.strip() == KEYWORD_SUGGESTION_DEFAULT_PROMPT.strip()
        return {"prompt": (stored or KEYWORD_SUGGESTION_DEFAULT_PROMPT), "is_default": is_default}

    def set_keyword_suggestion_prompt(self, prompt: str) -> dict[str, str]:
        """Persist a manager-provided keyword-suggestion system prompt."""
        normalized = prompt.strip() or KEYWORD_SUGGESTION_DEFAULT_PROMPT
        self._settings.set_value(KEYWORD_SUGGESTION_PROMPT_KEY, normalized)
        return {"prompt": normalized, "is_default": normalized == KEYWORD_SUGGESTION_DEFAULT_PROMPT.strip()}

    def reset_keyword_suggestion_prompt(self) -> dict[str, str]:
        """Clear any customised keyword-suggestion prompt so the default is used."""
        self._settings.delete(KEYWORD_SUGGESTION_PROMPT_KEY)
        return {"prompt": KEYWORD_SUGGESTION_DEFAULT_PROMPT, "is_default": True}

    def resolved_keyword_suggestion_prompt(self) -> str:
        """Return the active keyword-suggestion system prompt (default if none overridden)."""
        return self._settings.get_value(KEYWORD_SUGGESTION_PROMPT_KEY) or KEYWORD_SUGGESTION_DEFAULT_PROMPT

    # ---- LLM connection (API route / model / key) ---------------------

    def get_llm_config(self) -> dict[str, str | bool]:
        """Return the active LLM connection settings, including the real API key.

        The manager-facing settings page displays this value directly
        (behind a show/hide toggle in the UI) rather than masking it —
        it's the same key the manager themselves typed in, on an
        HR_ADMIN-only internal page, not a value from anyone else.
        """
        api_base = self._settings.get_value(LLM_API_BASE_KEY) or _CHAT_DEFAULT_API_BASE
        model = self._settings.get_value(LLM_MODEL_KEY) or _CHAT_DEFAULT_MODEL
        api_key = self._settings.get_value(LLM_API_KEY_KEY) or _CHAT_DEFAULT_API_KEY
        return {
            "api_base": api_base,
            "model": model,
            "api_key": api_key,
            "is_default": (
                api_base == _CHAT_DEFAULT_API_BASE
                and model == _CHAT_DEFAULT_MODEL
                and api_key == _CHAT_DEFAULT_API_KEY
            ),
        }

    def set_llm_config(self, *, api_base: str, model: str, api_key: str) -> dict[str, str | bool]:
        """Persist manager-provided LLM route/model/key settings.

        Unlike the old write-only design, the form always shows the real
        current value, so whatever is submitted (including an empty key)
        is the manager's actual intent — no more "blank means leave
        unchanged" special-casing.
        """
        self._settings.set_value(LLM_API_BASE_KEY, api_base.strip())
        self._settings.set_value(LLM_MODEL_KEY, model.strip())
        self._settings.set_value(LLM_API_KEY_KEY, api_key.strip())
        return self.get_llm_config()

    def reset_llm_config(self) -> dict[str, str | bool]:
        """Clear all LLM connection overrides, restoring the .env-configured defaults."""
        self._settings.delete(LLM_API_BASE_KEY)
        self._settings.delete(LLM_MODEL_KEY)
        self._settings.delete(LLM_API_KEY_KEY)
        return self.get_llm_config()

    def resolved_llm_overrides(self) -> dict[str, str | None]:
        """Return raw api_base/model/api_key overrides for the worker (None = use .env default)."""
        return {
            "api_base": self._settings.get_value(LLM_API_BASE_KEY),
            "model": self._settings.get_value(LLM_MODEL_KEY),
            "api_key": self._settings.get_value(LLM_API_KEY_KEY),
        }
