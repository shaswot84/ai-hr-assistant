"""Unit tests for the individual output-safety guards."""


from app.safety.contracts import FindingSeverity
from app.safety.output.guards.citations import CitationCoverageCheck
from app.safety.output.guards.evidence import EvidenceGate
from app.safety.output.guards.pii import PIIRedactionCheck
from app.safety.output.guards.topic import SensitiveTopicGate
from tests.unit.safety.helpers import make_context


class TestEvidenceGate:
    async def test_low_confidence_blocks(self):
        ctx = make_context(confidence=0.2)
        findings = await EvidenceGate().check(ctx)

        assert len(findings) == 1
        assert findings[0].guard == "evidence"
        assert findings[0].severity is FindingSeverity.BLOCK

    async def test_no_evidence_blocks(self):
        ctx = make_context(citations=0, confidence=0.0)
        findings = await EvidenceGate().check(ctx)

        assert findings[0].severity is FindingSeverity.BLOCK

    async def test_sufficient_evidence_passes(self):
        ctx = make_context(confidence=0.8, citations=2)
        assert await EvidenceGate().check(ctx) == []

    async def test_refusal_passes_even_when_ungrounded(self):
        ctx = make_context(response="I don't know.", confidence=0.1)
        assert await EvidenceGate().check(ctx) == []


class TestCitationCoverageCheck:
    async def test_missing_citations_flagged(self):
        ctx = make_context(response="Annual leave is 25 days.")
        findings = await CitationCoverageCheck().check(ctx)

        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.WARNING
        assert "no sources" in findings[0].message

    async def test_valid_citation_passes(self):
        ctx = make_context(response="Annual leave is 25 days. [1]")
        assert await CitationCoverageCheck().check(ctx) == []

    async def test_unretrieved_citation_flagged(self):
        ctx = make_context(response="Annual leave is 25 days. [2]")
        findings = await CitationCoverageCheck().check(ctx)

        assert len(findings) == 1
        assert "not retrieved" in findings[0].message

    async def test_require_citation_disabled(self):
        ctx = make_context(response="Annual leave is 25 days.")
        assert await CitationCoverageCheck(require_citation=False).check(ctx) == []


class TestPIIRedactionCheck:
    async def test_redacts_email_and_ssn(self):
        ctx = make_context(response="Contact jane@acme.com or 123-45-6789 for leave.")
        findings = await PIIRedactionCheck().check(ctx)

        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.WARNING
        assert findings[0].redacted_text is not None
        assert "jane@acme.com" not in findings[0].redacted_text
        assert "123-45-6789" not in findings[0].redacted_text
        assert findings[0].redacted_text.count("[REDACTED]") == 2

    async def test_clean_response_passes(self):
        ctx = make_context(response="Annual leave is 25 days. [1]")
        assert await PIIRedactionCheck().check(ctx) == []


class TestSensitiveTopicGate:
    async def test_sensitive_topic_blocks(self):
        ctx = make_context(topic="LEGAL_ADVICE")
        findings = await SensitiveTopicGate(["LEGAL_ADVICE"]).check(ctx)

        assert len(findings) == 1
        assert findings[0].severity is FindingSeverity.BLOCK

    async def test_unknown_topic_passes(self):
        ctx = make_context(topic="leave_policy")
        assert await SensitiveTopicGate(["LEGAL_ADVICE"]).check(ctx) == []

    async def test_no_topic_passes(self):
        ctx = make_context(topic=None)
        assert await SensitiveTopicGate(["LEGAL_ADVICE"]).check(ctx) == []
