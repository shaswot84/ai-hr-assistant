"""Optional LLM-as-judge: verifies responses against retrieved evidence."""

import json
import re

import httpx

from app.safety.contracts import FindingSeverity, GuardFinding, OutputContext
from app.safety.interfaces import ClaimVerifier

_PROMPT = """You are a factuality judge for an HR assistant. Determine whether
the assistant's answer is fully supported by the grounded context below, with
no invented facts, no contradictions, and no claims beyond the evidence.

GROUNDED CONTEXT:
{context}

ASSISTANT ANSWER:
{response}

Respond only with JSON: {{"grounded": true|false, "reason": "<short reason>"}}"""


class OllamaClaimVerifier(ClaimVerifier):
    """Verifies responses by calling an Ollama chat model.

    Fails closed: when the judge cannot be reached or returns an invalid
    verdict, the response is flagged for human review instead of being served
    as-is.
    """

    name = "claim_verifier"

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout_seconds: float = 30.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.model = model
        self._client = client or httpx.AsyncClient(
            base_url=base_url, timeout=timeout_seconds
        )

    async def verify(self, context: OutputContext) -> GuardFinding | None:
        if not context.citations:
            return None
        prompt = _PROMPT.format(
            context=context.grounded_context, response=context.response
        )
        try:
            raw = await self._generate(prompt)
        except httpx.HTTPError:
            return GuardFinding(
                guard=self.name,
                severity=FindingSeverity.WARNING,
                message="claim verification unavailable; response flagged for review",
            )
        grounded = self._parse_verdict(raw)
        if grounded is False:
            return GuardFinding(
                guard=self.name,
                severity=FindingSeverity.WARNING,
                message="answer contains claims not supported by retrieved evidence",
                details=raw.strip()[:500],
            )
        if grounded is None:
            return GuardFinding(
                guard=self.name,
                severity=FindingSeverity.WARNING,
                message="claim verification returned an invalid verdict",
                details=raw.strip()[:500],
            )
        return None

    async def _generate(self, prompt: str) -> str:
        response = await self._client.post(
            "/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
        )
        response.raise_for_status()
        return response.json().get("response", "")

    @staticmethod
    def _parse_verdict(raw: str) -> bool | None:
        text = raw.strip()
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return None
        return data.get("grounded")
