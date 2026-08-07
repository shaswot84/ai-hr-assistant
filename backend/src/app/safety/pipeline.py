"""Output Safety pipeline: reduces guard findings into a single verdict."""

from collections.abc import Sequence

from app.safety.contracts import (
    FindingSeverity,
    GuardFinding,
    GuardResult,
    GuardVerdict,
    OutputContext,
)
from app.safety.interfaces import ClaimVerifier, GuardCheck, ResponseGuard
from app.safety.output.judge.passthrough import PassThroughClaimVerifier


class OutputSafetyPipeline(ResponseGuard):
    """Runs every guard in order and reduces findings into a verdict.

    Verdict precedence: BLOCKED > REDACTED > FLAGGED_FOR_REVIEW > PASS.
    """

    def __init__(
        self,
        checks: Sequence[GuardCheck] | None = None,
        verifier: ClaimVerifier | None = None,
    ) -> None:
        self._checks = list(checks or [])
        self._verifier = verifier or PassThroughClaimVerifier()

    async def guard(self, context: OutputContext) -> GuardResult:
        findings = await self._run_checks(context)
        verdict, response = self._reduce(context, findings)
        return GuardResult(
            verdict=verdict,
            response=response,
            findings=findings,
            citations=context.citations,
            confidence=context.confidence,
        )

    async def _run_checks(self, context: OutputContext) -> list[GuardFinding]:
        findings: list[GuardFinding] = []
        for check in self._checks:
            findings.extend(await check.check(context))
        finding = await self._verifier.verify(context)
        if finding is not None:
            findings.append(finding)
        return findings

    @staticmethod
    def _reduce(
        context: OutputContext, findings: list[GuardFinding]
    ) -> tuple[GuardVerdict, str]:
        redacted = next(
            (f.redacted_text for f in findings if f.redacted_text is not None), None
        )
        if any(f.severity is FindingSeverity.BLOCK for f in findings):
            return GuardVerdict.BLOCKED, redacted or context.response
        if redacted is not None:
            return GuardVerdict.REDACTED, redacted
        if any(f.severity is FindingSeverity.WARNING for f in findings):
            return GuardVerdict.FLAGGED_FOR_REVIEW, context.response
        return GuardVerdict.PASS, context.response
