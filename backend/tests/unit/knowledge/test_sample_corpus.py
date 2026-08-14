"""The shipped sample KB corpus must stay consistent with the rest of the app.

The supervisor routes leave-policy questions to the knowledge agent (see
``agents/supervisor/route_intent.py``), which can only answer them if the
policy documents are indexed. These tests keep ``backend/sample_docs/``
aligned with the seeded leave types (``db/seed.py``) and the topics the
routing prompt promises — so a doc removed or a leave type renamed fails
loudly instead of silently breaking the chat demo.
"""

from __future__ import annotations

from pathlib import Path

from app.db.seed import SAMPLE_LEAVE_TYPES

SAMPLE_DOCS = Path(__file__).resolve().parents[3] / "sample_docs"


def _corpus_text() -> str:
    """All sample documents concatenated and normalized (no spaces/newlines)."""
    docs = "\n".join(p.read_text() for p in SAMPLE_DOCS.glob("*.md"))
    return docs.lower().replace(" ", "").replace("\n", "")


def test_every_seeded_leave_type_has_a_policy_doc():
    """Each leave type the leave agent transacts must have a KB policy doc —
    otherwise the knowledge agent cannot answer policy questions about it."""
    text = _corpus_text()
    for name, *_ in SAMPLE_LEAVE_TYPES:
        key = name.lower().replace(" ", "")
        assert key in text, f"no sample KB doc covers the seeded leave type {name!r}"


def test_sample_docs_are_nonempty_markdown_with_title_and_sections():
    """Each document is well-formed enough for the ingestion parser to chunk."""
    paths = sorted(SAMPLE_DOCS.glob("*.md"))
    assert paths, "sample_docs/ is empty — the knowledge base would have nothing to seed"
    for path in paths:
        text = path.read_text()
        assert text.strip(), f"{path.name} is empty"
        assert text.lstrip().startswith("# "), f"{path.name} must start with an H1 title"
        assert "## " in text, f"{path.name} must have at least one section"


def test_sample_docs_cover_routing_prompt_topics():
    """The routing prompt promises policy / procedures / dress code /
    onboarding answers — the shipped corpus should back the demo ones."""
    text = _corpus_text()
    for topic in ("dresscode", "onboarding", "annualleavepolicy"):
        assert topic in text, f"the sample KB corpus is missing the {topic!r} topic"
