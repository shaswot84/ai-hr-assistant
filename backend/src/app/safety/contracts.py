"""Shared types for the Output Safety layer.

The Output Safety layer inspects the final agent response together with the
retrieval evidence it was grounded on, and returns a verdict before the
response is served to the user.
"""

from dataclasses import dataclass, field
from enum import Enum

from app.knowledge.contracts import Citation


class GuardVerdict(str, Enum):
    """Final disposition of a guarded response."""

    PASS = "PASS"
    REDACTED = "REDACTED"
    BLOCKED = "BLOCKED"
    FLAGGED_FOR_REVIEW = "FLAGGED_FOR_REVIEW"


class FindingSeverity(str, Enum):
    """Severity of a single guard finding."""

    INFO = "INFO"
    WARNING = "WARNING"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class GuardFinding:
    """One violation or notice produced by a single guard check."""

    guard: str
    severity: FindingSeverity
    message: str
    details: str | None = None
    redacted_text: str | None = None


@dataclass(frozen=True)
class OutputContext:
    """What the output guards inspect: the response plus its evidence."""

    response: str
    grounded_context: str
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
    topic: str | None = None

    @property
    def has_evidence(self) -> bool:
        return bool(self.citations)


@dataclass(frozen=True)
class GuardResult:
    """Verdict returned to the caller together with the safe response."""

    verdict: GuardVerdict
    response: str
    findings: list[GuardFinding] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    confidence: float = 0.0
