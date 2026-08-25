"""Ollama Cloud-backed generation LLM for the Model Gateway."""

import json
from collections.abc import AsyncIterator

import httpx
from openinference.semconv.trace import SpanAttributes

from app.model_gateway.interfaces import LLM
from app.observability import set_llm_token_counts, trace_llm_call


class OllamaCloudLLM(LLM):
    """Calls Ollama's hosted chat API (``https://ollama.com``).

    Authentication is a Bearer token (the user's Ollama Cloud API key). The
    request shape matches the local Ollama ``/api/chat`` contract, so this
    adapter can point at any Ollama host by swapping the base URL.
    """

    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        timeout_seconds: float = 120.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._api_key = api_key
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds
        )

    async def complete(self, system: str, user: str) -> str:
        async with trace_llm_call(self.model, system_prompt=system, user_prompt=user) as span:
            response = await self._client.post(
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": False,
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
            content = payload["message"]["content"]
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, content)
            set_llm_token_counts(
                span,
                prompt_tokens=payload.get("prompt_eval_count"),
                completion_tokens=payload.get("eval_count"),
            )
            return content

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield completion chunks as the model generates them.

        With ``stream=true`` Ollama's ``/api/chat`` replies with one NDJSON
        line per token; each line carries ``message.content`` (and a trailing
        ``done=true`` line). A non-2xx response still raises.
        """
        async with trace_llm_call(self.model, system_prompt=system, user_prompt=user) as span:
            accumulated: list[str] = []
            async with self._client.stream(
                "POST",
                "/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user},
                    ],
                    "stream": True,
                },
                headers={"Authorization": f"Bearer {self._api_key}"},
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.strip():
                        continue
                    payload = json.loads(line)
                    if payload.get("done"):
                        set_llm_token_counts(
                            span,
                            prompt_tokens=payload.get("prompt_eval_count"),
                            completion_tokens=payload.get("eval_count"),
                        )
                        break
                    token = payload.get("message", {}).get("content", "")
                    if token:
                        accumulated.append(token)
                        yield token
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, "".join(accumulated))

    async def aclose(self) -> None:
        await self._client.aclose()
