"""Evidence gate: refuses answers that lack sufficient retrieval support."""

from app.config.settings import RetrievalSettings
from app.knowledge.confidence import LowConfidenceDetector
from app.safety.contracts import FindingSeverity, GuardFinding
from app.safety.interfaces import GuardCheck, OutputContext

_REFUSALS = (
    "i don't know",
    "i do not know",
    "i cannot answer",
    "i can't answer",
    "i'm not sure",
    "i am not sure",
    "not enough information",
    "insufficient information",
    "not available",
)


class EvidenceGate(GuardCheck):
    """Blocks responses that fail the low-confidence / min-sources gate.

    Responses that decline to answer (refusals) are allowed through so the
    assistant can honestly say "I don't know" without being blocked.
    """

    name = "evidence"

    def __init__(
        self,
        settings: RetrievalSettings | None = None,
        detector: LowConfidenceDetector | None = None,
        refusals: tuple[str, ...] = _REFUSALS,
    ) -> None:
        self._settings = settings or RetrievalSettings()
        self._detector = detector or LowConfidenceDetector(self._settings)
        self._refusals = refusals

    async def check(self, context: OutputContext) -> list[GuardFinding]:
        if self._is_refusal(context.response):
            return []
        if not self._detector.is_low(context.confidence, len(context.citations)):
            return []
        return [
            GuardFinding(
                guard=self.name,
                severity=FindingSeverity.BLOCK,
                message="refusing to answer without sufficient evidence",
                details=f"confidence={context.confidence:.2f}, sources={len(context.citations)}",
            )
        ]

    def _is_refusal(self, response: str) -> bool:
        lowered = response.strip().lower()
        return any(phrase in lowered for phrase in self._refusals)
