"""Unit tests for the claim verifiers (LLM-as-judge)."""

import json

import httpx

from app.safety.contracts import FindingSeverity
from app.safety.output.judge.ollama import OllamaClaimVerifier
from app.safety.output.judge.passthrough import PassThroughClaimVerifier
from tests.unit.safety.helpers import make_context


class TestPassThroughClaimVerifier:
    async def test_never_returns_a_finding(self):
        verifier = PassThroughClaimVerifier()
        assert await verifier.verify(make_context()) is None


class TestOllamaClaimVerifier:
    def _verifier(self, handler) -> OllamaClaimVerifier:
        client = httpx.AsyncClient(
            base_url="http://ollama:11434", transport=httpx.MockTransport(handler)
        )
        return OllamaClaimVerifier(
            "http://ollama:11434", "llama3.2", client=client
        )

    def _handler(self, verdict: str | None = None, status: int = 200):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                status, json={"model": "llama3.2", "response": verdict or ""}
            )

        return handler

    async def test_grounded_response_passes(self):
        verdict = json.dumps({"grounded": True, "reason": "supported"})
        verifier = self._verifier(self._handler(verdict))

        assert await verifier.verify(make_context()) is None

    async def test_ungrounded_response_flagged(self):
        verdict = json.dumps({"grounded": False, "reason": "not in evidence"})
        verifier = self._verifier(self._handler(verdict))

        finding = await verifier.verify(make_context())

        assert finding is not None
        assert finding.guard == "claim_verifier"
        assert finding.severity is FindingSeverity.WARNING
        assert "not supported" in finding.message

    async def test_invalid_verdict_flagged(self):
        verifier = self._verifier(self._handler("not json"))

        finding = await verifier.verify(make_context())

        assert finding is not None
        assert "invalid verdict" in finding.message

    async def test_markdown_fenced_json_parsed(self):
        verdict = '```json\n{"grounded": false, "reason": "x"}\n```'
        verifier = self._verifier(self._handler(verdict))

        finding = await verifier.verify(make_context())

        assert finding is not None
        assert finding.severity is FindingSeverity.WARNING

    async def test_http_error_fails_closed(self):
        verifier = self._verifier(self._handler(status=503))

        finding = await verifier.verify(make_context())

        assert finding is not None
        assert "unavailable" in finding.message

    async def test_no_evidence_skips_judge_call(self):
        called = False

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal called
            called = True
            return httpx.Response(200, json={"response": "{}"})

        verifier = self._verifier(handler)
        assert await verifier.verify(make_context(citations=0)) is None
        assert called is False
