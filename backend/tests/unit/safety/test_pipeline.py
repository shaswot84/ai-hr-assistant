"""Unit tests for the OutputSafetyPipeline verdict reduction."""

import pytest

from app.safety.contracts import (
    FindingSeverity,
    GuardFinding,
    GuardVerdict,
    OutputContext,
)
from app.safety.interfaces import ClaimVerifier, GuardCheck
from app.safety.output.judge.passthrough import PassThroughClaimVerifier
from app.safety.pipeline import OutputSafetyPipeline
from tests.unit.safety.helpers import make_context


class FindingGuard(GuardCheck):
    """Produces a fixed set of findings for pipeline tests."""

    name = "fake"

    def __init__(self, *findings: GuardFinding) -> None:
        self._findings = list(findings)

    async def check(self, context: OutputContext) -> list[GuardFinding]:
        return self._findings


class FindingVerifier(ClaimVerifier):
    """Produces a fixed verifier finding."""

    model = "fake"

    def __init__(self, finding: GuardFinding | None) -> None:
        self._finding = finding

    async def verify(self, context: OutputContext) -> GuardFinding | None:
        return self._finding


def warning(message: str = "warn") -> GuardFinding:
    return GuardFinding(guard="fake", severity=FindingSeverity.WARNING, message=message)


def block(message: str = "block") -> GuardFinding:
    return GuardFinding(guard="fake", severity=FindingSeverity.BLOCK, message=message)


@pytest.mark.asyncio
async def test_no_checks_pass_through():
    pipeline = OutputSafetyPipeline(checks=[])
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.PASS
    assert result.response == "Annual leave is 25 days. [1]"
    assert result.findings == []


@pytest.mark.asyncio
async def test_warning_flags_for_review():
    pipeline = OutputSafetyPipeline(checks=[FindingGuard(warning())])
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.FLAGGED_FOR_REVIEW
    assert result.response == make_context().response


@pytest.mark.asyncio
async def test_redaction_yields_redacted_response():
    redacted_finding = GuardFinding(
        guard="pii",
        severity=FindingSeverity.WARNING,
        message="redacted sensitive value(s)",
        redacted_text="Annual leave is [REDACTED] days. [1]",
    )
    pipeline = OutputSafetyPipeline(checks=[FindingGuard(redacted_finding)])
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.REDACTED
    assert result.response == "Annual leave is [REDACTED] days. [1]"


@pytest.mark.asyncio
async def test_block_beats_warning():
    pipeline = OutputSafetyPipeline(checks=[FindingGuard(warning(), block())])
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.BLOCKED


@pytest.mark.asyncio
async def test_block_beats_redaction_but_keeps_sanitized_text():
    redacted = GuardFinding(
        guard="pii",
        severity=FindingSeverity.WARNING,
        message="redacted",
        redacted_text="no [REDACTED] here",
    )
    pipeline = OutputSafetyPipeline(checks=[FindingGuard(redacted, block())])
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.BLOCKED
    assert result.response == "no [REDACTED] here"


@pytest.mark.asyncio
async def test_verifier_finding_is_appended():
    pipeline = OutputSafetyPipeline(
        checks=[], verifier=FindingVerifier(warning("unsupported"))
    )
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.FLAGGED_FOR_REVIEW
    assert len(result.findings) == 1
    assert result.findings[0].message == "unsupported"


@pytest.mark.asyncio
async def test_verifier_without_finding_passes():
    pipeline = OutputSafetyPipeline(checks=[], verifier=FindingVerifier(None))
    result = await pipeline.guard(make_context())

    assert result.verdict is GuardVerdict.PASS


@pytest.mark.asyncio
async def test_default_verifier_is_passthrough():
    pipeline = OutputSafetyPipeline(checks=[])
    assert isinstance(pipeline._verifier, PassThroughClaimVerifier)
