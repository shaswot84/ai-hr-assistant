"""Shared fixtures/helpers for the Output Safety tests."""

import uuid

from app.knowledge.contracts import Citation
from app.safety.contracts import OutputContext


def make_citation(title: str = "Leave Policy") -> Citation:
    return Citation(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title=title,
        category="POLICY",
    )


def make_context(
    *,
    response: str = "Annual leave is 25 days. [1]",
    grounded_context: str = "Annual leave is 25 days per year.",
    citations: int = 1,
    confidence: float = 0.8,
    topic: str | None = None,
) -> OutputContext:
    return OutputContext(
        response=response,
        grounded_context=grounded_context,
        citations=[make_citation() for _ in range(citations)],
        confidence=confidence,
        topic=topic,
    )
