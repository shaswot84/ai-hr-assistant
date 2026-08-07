"""Sensitive-value redaction: removes PII from responses before serving."""

import re

from app.safety.contracts import FindingSeverity, GuardFinding
from app.safety.interfaces import GuardCheck, OutputContext

_PII_PATTERNS: dict[str, re.Pattern[str]] = {
    "email": re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"),
    "phone": re.compile(r"(?<!\w)(?:\+?\d[\d\s().-]{6,}\d)(?!\w)"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,19}\b"),
    "salary": re.compile(r"\$\s?\d{1,3}(?:,\d{3})+(?:\.\d{2})?"),
}


class PIIRedactionCheck(GuardCheck):
    """Redacts sensitive values, returning the sanitized response."""

    name = "pii"

    def __init__(
        self,
        patterns: dict[str, re.Pattern[str]] | None = None,
        redaction_token: str = "[REDACTED]",
    ) -> None:
        self._patterns = patterns if patterns is not None else _PII_PATTERNS
        self._token = redaction_token

    async def check(self, context: OutputContext) -> list[GuardFinding]:
        redacted = context.response
        labels: list[str] = []
        for label, pattern in self._patterns.items():
            matches = pattern.findall(redacted)
            if matches:
                redacted = pattern.sub(self._token, redacted)
                labels.append(label)
        if not labels:
            return []
        return [
            GuardFinding(
                guard=self.name,
                severity=FindingSeverity.WARNING,
                message=f"redacted sensitive value(s): {', '.join(sorted(labels))}",
                redacted_text=redacted,
            )
        ]
