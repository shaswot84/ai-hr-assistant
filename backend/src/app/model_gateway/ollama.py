from __future__ import annotations

import json
import re
from typing import Any

import httpx

from app.config.settings import get_settings
from app.model_gateway.provider import ChatProvider, ChatProviderError


class OllamaChatProvider(ChatProvider):
    """Hosted Ollama API via an OpenAI-compatible chat/completions endpoint.

    Key, base URL, and model default to settings (.env) but can each be
    overridden per-call — the manager-editable LLM config on the Settings
    page is stored in `app_setting` and passed in here by the worker, so
    changes take effect on the next evaluation with no restart needed.
    """

    def __init__(
        self,
        *,
        api_base: str | None = None,
        model: str | None = None,
        api_key: str | None = None,
    ) -> None:
        """Load endpoint, model, key, and timeout, preferring any given overrides.

        `None` means "no override was given" (fall back to the .env-configured
        default); an empty string is a real, explicit override (a manager
        cleared the field in Settings) and must be honored as blank rather
        than silently falling back — `or` can't tell those two cases apart
        since `""` and `None` are both falsy.
        """
        self._settings = get_settings()
        self._base = (self._settings.chat.api_base if api_base is None else api_base).removesuffix("/")
        self._model = self._settings.chat.model if model is None else model
        self._api_key = self._settings.chat.api_key if api_key is None else api_key
        self._timeout = self._settings.chat.request_timeout

    def is_configured(self) -> bool:
        """Return True if a real (non-placeholder) Ollama API key is present."""
        key = self._api_key
        # A placeholder value (e.g. "your-ollama-api-key") is not a real key.
        return bool(key) and not ("your-" in key or key.startswith("<"))

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Call the hosted Ollama chat/completions endpoint and return parsed JSON.

        Raises ChatProviderError if the key is missing, the request fails or
        times out, or the response cannot be parsed as JSON.
        """
        if not self.is_configured():
            raise ChatProviderError("Ollama API key is not configured.")
        url = f"{self._base}/v1/chat/completions"
        payload = {
            "model": self._model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                res = await client.post(url, json=payload, headers=headers)
        except httpx.TimeoutException as err:
            raise ChatProviderError("The AI scoring request timed out.") from err
        except httpx.HTTPError as err:
            raise ChatProviderError(f"Could not reach Ollama API: {err}") from err

        if res.status_code >= 400:
            raise ChatProviderError(
                f"Ollama API error ({res.status_code}): {res.text[:300]}"
            )
        content = (res.json().get("choices") or [{}])[0].get("message", {}).get("content")
        if not content:
            raise ChatProviderError("Ollama API returned an empty response.")

        json_text = _extract_json(content)
        try:
            return json.loads(json_text)
        except json.JSONDecodeError as err:
            raise ChatProviderError("The model did not return valid JSON.") from err


def _extract_json(text: str) -> str:
    """Return the JSON substring from a model reply, stripping code fences if any."""
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)```", text, re.IGNORECASE)
    candidate = fenced.group(1) if fenced else text
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end == -1 or end < start:
        return candidate.strip()
    return candidate[start : end + 1]