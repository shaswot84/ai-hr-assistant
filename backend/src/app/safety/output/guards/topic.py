"""Sensitive-topic gate: routes high-risk topics to human review."""

from app.safety.contracts import FindingSeverity, GuardFinding
from app.safety.interfaces import GuardCheck, OutputContext


class SensitiveTopicGate(GuardCheck):
    """Blocks responses whose topic requires a human decision."""

    name = "sensitive_topic"

    def __init__(self, sensitive_topics: list[str] | None = None) -> None:
        self._topics = {t.upper() for t in (sensitive_topics or [])}

    async def check(self, context: OutputContext) -> list[GuardFinding]:
        if context.topic is None or context.topic.upper() not in self._topics:
            return []
        return [
            GuardFinding(
                guard=self.name,
                severity=FindingSeverity.BLOCK,
                message="response in a sensitive topic requires human review",
                details=context.topic,
            )
        ]
