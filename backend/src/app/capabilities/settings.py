from __future__ import annotations

from app.config.settings import ChatSettings
from app.evaluation.keyword_suggestion import (
    DEFAULT_SYSTEM_PROMPT as KEYWORD_SUGGESTION_DEFAULT_PROMPT,
)
from app.evaluation.resume_structuring import (
    DEFAULT_SYSTEM_PROMPT as STRUCTURING_DEFAULT_SYSTEM_PROMPT,
)
from app.evaluation.resume_structuring import USER_PROMPT as STRUCTURING_DEFAULT_USER_PROMPT
from app.evaluation.scoring import DEFAULT_SYSTEM_PROMPT as SCORING_DEFAULT_SYSTEM_PROMPT
from app.evaluation.scoring import USER_PROMPT as SCORING_DEFAULT_USER_PROMPT
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

#: Keys used to store manager-overridden LLM prompts — one pair (system +
#: task/user template) per LLM call in the recruitment pipeline, plus the
#: keyword-suggestion prompt which has no editable user template (its
#: schema/rules aren't manager-facing).
RESUME_REVIEW_PROMPT_KEY = "RESUME_REVIEW_SYSTEM_PROMPT"
RESUME_REVIEW_USER_PROMPT_KEY = "RESUME_REVIEW_USER_PROMPT"
STRUCTURING_SYSTEM_PROMPT_KEY = "RESUME_STRUCTURING_SYSTEM_PROMPT"
STRUCTURING_USER_PROMPT_KEY = "RESUME_STRUCTURING_USER_PROMPT"
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

    Manager-editable settings (the recruitment-pipeline prompts, the LLM
    connection) are stored directly in `.env` via `EnvFileSettingRepo`,
    which re-reads the file on every call — so a change made through the
    API takes effect on the worker's very next job, no restart needed.
    """

    def __init__(self) -> None:
        self._settings = EnvFileSettingRepo()

    # ---- generic prompt get/set/reset/resolve --------------------------
    #
    # Every manager-editable prompt (resume-review system/user, keyword-
    # suggestion system, resume-structuring system/user) follows the exact
    # same shape — stored value or default, with an `is_default` flag for
    # the UI. Implemented once here; the named methods below are just typed,
    # discoverable wrappers around a (key, default) pair so callers and
    # routes don't have to pass raw setting keys around.

    def _get_prompt(self, key: str, default: str) -> dict[str, str]:
        stored = self._settings.get_value(key)
        is_default = not stored or stored.strip() == default.strip()
        return {"prompt": (stored or default), "is_default": is_default}

    def _set_prompt(self, key: str, default: str, prompt: str) -> dict[str, str]:
        normalized = prompt.strip() or default
        self._settings.set_value(key, normalized)
        return {"prompt": normalized, "is_default": normalized == default.strip()}

    def _reset_prompt(self, key: str, default: str) -> dict[str, str]:
        self._settings.delete(key)
        return {"prompt": default, "is_default": True}

    def _resolved_prompt(self, key: str, default: str) -> str:
        return self._settings.get_value(key) or default

    # ---- resume-review system prompt (the ATS-screener persona) -------

    def get_resume_review_prompt(self) -> dict[str, str]:
        return self._get_prompt(RESUME_REVIEW_PROMPT_KEY, SCORING_DEFAULT_SYSTEM_PROMPT)

    def set_resume_review_prompt(self, prompt: str) -> dict[str, str]:
        return self._set_prompt(RESUME_REVIEW_PROMPT_KEY, SCORING_DEFAULT_SYSTEM_PROMPT, prompt)

    def reset_resume_review_prompt(self) -> dict[str, str]:
        return self._reset_prompt(RESUME_REVIEW_PROMPT_KEY, SCORING_DEFAULT_SYSTEM_PROMPT)

    def resolved_prompt(self) -> str:
        """Return the active resume-review system prompt for evaluation use."""
        return self._resolved_prompt(RESUME_REVIEW_PROMPT_KEY, SCORING_DEFAULT_SYSTEM_PROMPT)

    # ---- resume-review user/task prompt (schema + scoring instructions) -

    def get_resume_review_user_prompt(self) -> dict[str, str]:
        return self._get_prompt(RESUME_REVIEW_USER_PROMPT_KEY, SCORING_DEFAULT_USER_PROMPT)

    def set_resume_review_user_prompt(self, prompt: str) -> dict[str, str]:
        return self._set_prompt(RESUME_REVIEW_USER_PROMPT_KEY, SCORING_DEFAULT_USER_PROMPT, prompt)

    def reset_resume_review_user_prompt(self) -> dict[str, str]:
        return self._reset_prompt(RESUME_REVIEW_USER_PROMPT_KEY, SCORING_DEFAULT_USER_PROMPT)

    def resolved_resume_review_user_prompt(self) -> str:
        """Return the active resume-review task template for evaluation use."""
        return self._resolved_prompt(RESUME_REVIEW_USER_PROMPT_KEY, SCORING_DEFAULT_USER_PROMPT)

    # ---- resume-structuring system prompt (the extraction persona) ----

    def get_structuring_system_prompt(self) -> dict[str, str]:
        return self._get_prompt(STRUCTURING_SYSTEM_PROMPT_KEY, STRUCTURING_DEFAULT_SYSTEM_PROMPT)

    def set_structuring_system_prompt(self, prompt: str) -> dict[str, str]:
        return self._set_prompt(
            STRUCTURING_SYSTEM_PROMPT_KEY, STRUCTURING_DEFAULT_SYSTEM_PROMPT, prompt
        )

    def reset_structuring_system_prompt(self) -> dict[str, str]:
        return self._reset_prompt(STRUCTURING_SYSTEM_PROMPT_KEY, STRUCTURING_DEFAULT_SYSTEM_PROMPT)

    def resolved_structuring_system_prompt(self) -> str:
        """Return the active resume-structuring system prompt for evaluation use."""
        return self._resolved_prompt(
            STRUCTURING_SYSTEM_PROMPT_KEY, STRUCTURING_DEFAULT_SYSTEM_PROMPT
        )

    # ---- resume-structuring user/task prompt (extraction schema) ------

    def get_structuring_user_prompt(self) -> dict[str, str]:
        return self._get_prompt(STRUCTURING_USER_PROMPT_KEY, STRUCTURING_DEFAULT_USER_PROMPT)

    def set_structuring_user_prompt(self, prompt: str) -> dict[str, str]:
        return self._set_prompt(
            STRUCTURING_USER_PROMPT_KEY, STRUCTURING_DEFAULT_USER_PROMPT, prompt
        )

    def reset_structuring_user_prompt(self) -> dict[str, str]:
        return self._reset_prompt(STRUCTURING_USER_PROMPT_KEY, STRUCTURING_DEFAULT_USER_PROMPT)

    def resolved_structuring_user_prompt(self) -> str:
        """Return the active resume-structuring task template for evaluation use."""
        return self._resolved_prompt(STRUCTURING_USER_PROMPT_KEY, STRUCTURING_DEFAULT_USER_PROMPT)

    # ---- keyword-suggestion system prompt ------------------------------

    def get_keyword_suggestion_prompt(self) -> dict[str, str]:
        return self._get_prompt(KEYWORD_SUGGESTION_PROMPT_KEY, KEYWORD_SUGGESTION_DEFAULT_PROMPT)

    def set_keyword_suggestion_prompt(self, prompt: str) -> dict[str, str]:
        return self._set_prompt(
            KEYWORD_SUGGESTION_PROMPT_KEY, KEYWORD_SUGGESTION_DEFAULT_PROMPT, prompt
        )

    def reset_keyword_suggestion_prompt(self) -> dict[str, str]:
        return self._reset_prompt(KEYWORD_SUGGESTION_PROMPT_KEY, KEYWORD_SUGGESTION_DEFAULT_PROMPT)

    def resolved_keyword_suggestion_prompt(self) -> str:
        """Return the active keyword-suggestion system prompt (default if none overridden)."""
        return self._resolved_prompt(
            KEYWORD_SUGGESTION_PROMPT_KEY, KEYWORD_SUGGESTION_DEFAULT_PROMPT
        )

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
