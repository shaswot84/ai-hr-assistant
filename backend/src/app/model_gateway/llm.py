"""Ollama Cloud-backed generation LLM for the Model Gateway."""

import json
from collections.abc import AsyncIterator

import httpx

from app.model_gateway.interfaces import LLM


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
        return payload["message"]["content"]

    async def stream(self, system: str, user: str) -> AsyncIterator[str]:
        """Yield completion chunks as the model generates them.

        With ``stream=true`` Ollama's ``/api/chat`` replies with one NDJSON
        line per token; each line carries ``message.content`` (and a trailing
        ``done=true`` line). A non-2xx response still raises.
        """
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
                    break
                token = payload.get("message", {}).get("content", "")
                if token:
                    yield token

    async def aclose(self) -> None:
        await self._client.aclose()
