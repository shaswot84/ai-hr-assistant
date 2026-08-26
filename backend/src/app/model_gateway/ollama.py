from __future__ import annotations

import json
import re
from typing import Any

import httpx
from openinference.semconv.trace import SpanAttributes

from app.config.settings import get_settings
from app.model_gateway.provider import ChatProvider, ChatProviderError
from app.observability import set_llm_token_counts, trace_llm_call



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
        client: httpx.AsyncClient | None = None,
    ) -> None:
        """Load endpoint, model, key, and timeout, preferring any given overrides.

        `None` means "no override was given" (fall back to chat settings, or LLM
        settings); an empty string is a real, explicit override (a manager
        cleared the field in Settings) and must be honored as blank rather
        than silently falling back. ``client`` is a test injection point
        (defaults to a per-call AsyncClient).
        """
        self._settings = get_settings()
        chat = getattr(self._settings, "chat", None)
        llm = getattr(self._settings, "llm", None)
        default_base = (getattr(chat, "api_base", None) or getattr(llm, "url", None) or "")
        default_model = (getattr(chat, "model", None) or getattr(llm, "model", None) or "")
        default_key = (getattr(chat, "api_key", None) or getattr(llm, "api_key", None) or "")

        self._base = (default_base if api_base is None else api_base).removesuffix("/")
        self._model = default_model if model is None else model
        self._api_key = default_key if api_key is None else api_key
        self._timeout = getattr(chat, "request_timeout", 30.0)
        self._client = client

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

        async with trace_llm_call(
            self._model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            invocation_parameters={"temperature": temperature, "response_format": "json_object"},
        ) as span:
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
                async with self._client or httpx.AsyncClient(timeout=self._timeout) as client:
                    res = await client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as err:
                raise ChatProviderError("The AI scoring request timed out.") from err
            except httpx.HTTPError as err:
                raise ChatProviderError(f"Could not reach Ollama API: {err}") from err

            if res.status_code >= 400:
                raise ChatProviderError(
                    f"Ollama API error ({res.status_code}): {res.text[:300]}"
                )
            res_data = res.json()
            usage = res_data.get("usage") or {}
            set_llm_token_counts(
                span,
                prompt_tokens=usage.get("prompt_tokens"),
                completion_tokens=usage.get("completion_tokens"),
                total_tokens=usage.get("total_tokens"),
            )
            content = (res_data.get("choices") or [{}])[0].get("message", {}).get("content")
            if not content:
                raise ChatProviderError("Ollama API returned an empty response.")

            json_text = _extract_json(content)
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, json_text)
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