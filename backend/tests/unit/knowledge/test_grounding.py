"""Unit tests for the grounding/citation context builder."""

import uuid
from dataclasses import replace

from app.knowledge.contracts import RetrievedChunk
from app.knowledge.grounding import GroundingContextBuilder


def make_chunk(text: str, title: str = "Leave Policy", section: str | None = "Annual Leave", page: int | None = 3) -> RetrievedChunk:
    """Build a chunk with configurable location metadata."""
    return RetrievedChunk(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title=title,
        category="POLICY",
        page=page,
        section_title=section,
        text=text,
        retrieval_score=0.5,
    )


def test_build_produces_blocks_and_citations():
    chunk = make_chunk("Annual leave accrues at 1.5 days per month.")
    context, citations = GroundingContextBuilder().build([chunk])

    assert "[1] (Leave Policy, Annual Leave, p.3)" in context
    assert "Annual leave accrues at 1.5 days per month." in context
    assert len(citations) == 1
    assert citations[0].document_title == "Leave Policy"
    assert citations[0].chunk_id == chunk.chunk_id
    assert citations[0].page == 3


def test_build_without_location_metadata():
    chunk = make_chunk("Text", section=None, page=None)
    context, _ = GroundingContextBuilder().build([chunk])
    assert context == "[1] (Leave Policy) Text"


def test_build_respects_max_chunks():
    chunks = [make_chunk(f"chunk {i}") for i in range(5)]
    context, citations = GroundingContextBuilder(max_chunks=2).build(chunks)
    assert context.count("[") == 2
    assert len(citations) == 2


def test_build_renders_parent_section_context():
    chunk = make_chunk("Sign the contract.")
    chunk = replace(chunk, parent_context="Onboarding: equipment, orientation.")
    context, _ = GroundingContextBuilder().build([chunk])

    assert "Section: Annual Leave\nOnboarding: equipment, orientation." in context
    # Leaf text still present and cited.
    assert "Sign the contract." in context
    assert "[1]" in context


def test_build_dedupes_leaf_text_from_parent_context():
    text = "Annual | 20 | Manager"
    chunk = make_chunk(text)
    chunk = replace(chunk, parent_context=f"Holidays\n\n{text}")
    context, _ = GroundingContextBuilder().build([chunk])

    # The leaf text should appear exactly once in the rendered block.
    assert context.count(text) == 1
    assert "Section: Annual Leave\nHolidays" in context


def test_build_without_parent_context_unchanged():
    chunk = make_chunk("Plain leaf text.")
    context, _ = GroundingContextBuilder().build([chunk])
    assert "Section:" not in context
    assert context == "[1] (Leave Policy, Annual Leave, p.3) Plain leaf text."
