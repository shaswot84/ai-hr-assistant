"""Citation coverage: claims must be traceable to retrieved evidence."""

from app.knowledge.markers import parse_marker_set
from app.safety.contracts import FindingSeverity, GuardFinding
from app.safety.interfaces import GuardCheck, OutputContext


class CitationCoverageCheck(GuardCheck):
    """Flags responses that cite nothing or cite sources never retrieved."""

    name = "citations"

    def __init__(self, require_citation: bool = True) -> None:
        self._require_citation = require_citation

    async def check(self, context: OutputContext) -> list[GuardFinding]:
        findings: list[GuardFinding] = []
        markers = parse_marker_set(context.response)
        valid = set(range(1, len(context.citations) + 1))
        invalid = sorted(markers - valid)
        if invalid:
            findings.append(
                GuardFinding(
                    guard=self.name,
                    severity=FindingSeverity.WARNING,
                    message="response cites sources that were not retrieved",
                    details=f"markers={invalid}",
                )
            )
        if self._require_citation and context.citations and not markers:
            findings.append(
                GuardFinding(
                    guard=self.name,
                    severity=FindingSeverity.WARNING,
                    message="response makes claims but cites no sources",
                )
            )
        return findings
