"""Unit tests for the knowledge agent (rewrite -> retrieve -> stream -> verify).

Covers query rewriting, token streaming, honest refusals, claim tracking
(``[N]`` markers -> verified citations), and the output-safety wiring
(block -> refusal, flagged -> one repair pass). Uses fake LLM / knowledge
service / guard so nothing touches a model server or a database.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.knowledge_agent.agent import (
    KnowledgeTurn,
    fallback_message,
    rewrite_query,
    stream_knowledge_turn,
    strip_invalid_markers,
    verified_citations,
)
from app.knowledge.contracts import Citation, KnowledgeResult
from app.model_gateway.interfaces import LLM
from app.safety.contracts import (
    FindingSeverity,
    GuardFinding,
    GuardResult,
    GuardVerdict,
)
from app.safety.output.guards.citations import CitationCoverageCheck
from app.safety.pipeline import OutputSafetyPipeline


class FakeLLM(LLM):
    """An LLM stub with a canned completion."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


class ScriptedLLM(LLM):
    """An LLM stub returning responses in order (routing, then repair, ...)."""

    model = "fake"

    def __init__(self, responses: list[str]) -> None:
        self.responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.responses.pop(0) if self.responses else ""


class FakeKnowledgeService:
    """A KnowledgeService stub capturing what the node asks it."""

    def __init__(
        self,
        result: KnowledgeResult,
        answer: str | None = "Grounded answer from the policy. [1]",
    ) -> None:
        self.result = result
        self.answer = answer
        self.retrieve_queries: list[str] = []
        self.stream_queries: list[str] = []
        self.stream_histories: list[str | None] = []

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        self.retrieve_queries.append(query)
        return self.result

    async def stream_answer(self, query: str, result: KnowledgeResult, *, history=None):
        self.stream_queries.append(query)
        self.stream_histories.append(history)
        if self.answer:
            yield self.answer


class FakeGuard:
    """A guard stub returning a canned GuardResult."""

    def __init__(self, result: GuardResult) -> None:
        self.result = result

    async def guard(self, context) -> GuardResult:
        return self.result


def make_result(*, low_confidence: bool = False, confidence: float = 0.9) -> KnowledgeResult:
    """A retrieval result with one citation (unless low confidence)."""
    citation = Citation(
        chunk_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        document_version_id=uuid.uuid4(),
        version_number=1,
        document_title="Leave Policy",
        category="POLICY",
        page=2,
        section_title="Annual Leave",
    )
    return KnowledgeResult(
        grounded_context="Annual leave accrues at 1.5 days per month. (Leave Policy)",
        citations=[] if low_confidence else [citation],
        confidence=confidence,
        chunks=[],
        low_confidence=low_confidence,
    )


class EventCollector:
    """Captures the events the turn streams through its writer."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    def __call__(self, event: dict) -> None:
        self.events.append(event)


# --- query rewriting ------------------------------------------------------


@pytest.mark.asyncio
async def test_rewrite_query_uses_llm():
    """With an LLM, a context-dependent follow-up becomes self-contained."""
    llm = FakeLLM("What is the sick leave policy?")
    history = [
        HumanMessage(content="How much annual leave do I have?"),
        AIMessage(content="You have 15 days remaining."),
    ]

    rewritten = await rewrite_query(llm, "what about sick leave?", history)
    assert rewritten == "What is the sick leave policy?"

    _, user_prompt = llm.calls[0]
    assert "How much annual leave do I have?" in user_prompt
    assert "what about sick leave?" in user_prompt


@pytest.mark.asyncio
async def test_rewrite_query_without_llm_returns_query():
    """No LLM configured -> the raw query is used for retrieval."""
    assert await rewrite_query(None, "what about sick leave?", []) == "what about sick leave?"


@pytest.mark.asyncio
async def test_rewrite_query_falls_back_on_failure():
    """A failing rewrite LLM never breaks retrieval."""

    class BrokenLLM(FakeLLM):
        async def complete(self, system: str, user: str) -> str:
            raise RuntimeError("model down")

    assert await rewrite_query(BrokenLLM("x"), "the original question", []) == "the original question"


# --- turn orchestration + claim tracking ----------------------------------


@pytest.mark.asyncio
async def test_stream_knowledge_turn_rewrites_then_retrieves():
    """The turn retrieves on the REWRITTEN query, streams, and verifies claims."""
    llm = FakeLLM("What is the sick leave policy?")
    service = FakeKnowledgeService(make_result())
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="what about sick leave?", history=[], writer=writer
    )

    assert service.retrieve_queries == ["What is the sick leave policy?"]
    assert service.stream_queries == ["What is the sick leave policy?"]

    # Streamed events: retrieval metadata first, then the answer token.
    types = [e["type"] for e in writer.events]
    assert types == ["retrieval", "token"]
    assert writer.events[0]["rewritten_query"] == "What is the sick leave policy?"
    assert writer.events[0]["result"] is service.result

    # The answer cites [1] -> exactly the one retrieved citation is verified.
    assert state_update["answer"] == "Grounded answer from the policy. [1]"
    assert state_update["agent"] == "knowledge"
    assert state_update["confidence"] == 0.9
    assert state_update["safety"] == "PASS"
    assert [c.document_title for c in state_update["citations"]] == ["Leave Policy"]
    assert state_update["messages"][-1].content == "Grounded answer from the policy. [1]"


@pytest.mark.asyncio
async def test_stream_knowledge_turn_includes_history_in_generation():
    """The generation prompt receives a compact history block."""
    service = FakeKnowledgeService(make_result())
    writer = EventCollector()
    history = [HumanMessage(content="How much annual leave do I have?")]

    await stream_knowledge_turn(
        service=service, llm=FakeLLM("rewritten q"), query="what about sick leave?",
        history=history, writer=writer,
    )

    assert service.stream_histories == ["User: How much annual leave do I have?"]


@pytest.mark.asyncio
async def test_verified_citations_parses_markers():
    """Only markers present in the text count, and only within the retrieved set."""
    c1, c2 = make_result().citations[0], make_result().citations[0]
    result = KnowledgeResult(
        grounded_context="",
        citations=[c1, c2],
        confidence=0.9,
        chunks=[],
        low_confidence=False,
    )
    text = "Annual leave accrues at 1.5 days [1]. Sick leave is separate [2]."

    verified = verified_citations(text, result.citations)
    assert [c.document_title for c in verified] == ["Leave Policy", "Leave Policy"]

    # Out-of-range marker [5] is never verified; an uncited answer verifies nothing.
    assert verified_citations("No markers at all.", result.citations) == []
    assert verified_citations("Claims a source [5].", result.citations) == []


@pytest.mark.asyncio
async def test_strip_invalid_markers():
    """Markers for never-retrieved sources are removed from the text."""
    stripped = strip_invalid_markers("One claim [1] and a bogus one [9].", citation_count=1)
    assert stripped == "One claim [1] and a bogus one ."


@pytest.mark.asyncio
async def test_low_confidence_streams_honest_message():
    """Low-confidence retrieval streams a message, never tokens or a fake answer."""
    service = FakeKnowledgeService(make_result(low_confidence=True), answer="should not be used")
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=FakeLLM("rewritten"), query="q", history=[], writer=writer
    )

    assert [e["type"] for e in writer.events] == ["retrieval", "message"]
    assert "couldn't find enough evidence" in writer.events[1]["text"]
    assert "should not be used" not in writer.events[1]["text"]
    assert "couldn't find enough evidence" in state_update["answer"]
    assert state_update["citations"] == []
    assert state_update["safety"] == "PASS"


@pytest.mark.asyncio
async def test_no_answer_with_evidence_serves_grounded_context():
    """Evidence found but no generated answer -> grounded-context message."""
    service = FakeKnowledgeService(make_result(), answer=None)
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=service, llm=None, query="annual leave accrual", history=[], writer=writer
    )

    assert [e["type"] for e in writer.events] == ["retrieval", "message"]
    assert state_update["answer"] == "Annual leave accrues at 1.5 days per month. (Leave Policy)"
    # The fallback text carries no [N] markers -> nothing is "verified".
    assert state_update["citations"] == []


# --- output-safety wiring --------------------------------------------------


@pytest.mark.asyncio
async def test_blocked_answer_becomes_refusal():
    """A BLOCK verdict (e.g. evidence gate) replaces the answer with a refusal."""
    guard = FakeGuard(
        GuardResult(
            verdict=GuardVerdict.BLOCKED,
            response="should not be served",
            findings=[
                GuardFinding(
                    guard="evidence",
                    severity=FindingSeverity.BLOCK,
                    message="refusing to answer without sufficient evidence",
                )
            ],
        )
    )
    writer = EventCollector()

    state_update = await stream_knowledge_turn(
        service=FakeKnowledgeService(make_result(), answer="should not be served"),
        llm=FakeLLM("rewritten"),
        query="q",
        history=[],
        writer=writer,
        guard=guard,
    )

    assert "couldn't find enough evidence" in state_update["answer"]
    assert "should not be served" not in state_update["answer"]
    assert state_update["citations"] == []
    assert state_update["safety"] == GuardVerdict.BLOCKED.value


@pytest.mark.asyncio
async def test_flagged_answer_gets_one_repair_pass():
    """Claims without markers -> FLAGGED -> one repair pass restores traceability."""
    guard = OutputSafetyPipeline(checks=[CitationCoverageCheck()])
    # First LLM call rewrites the query; second repairs the draft with markers.
    llm = ScriptedLLM(["What is the sick leave policy?", "The policy grants 15 sick days. [1]"])
    writer = EventCollector()
    service = FakeKnowledgeService(make_result(), answer="The policy grants 15 sick days.")

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="sick leave", history=[], writer=writer, guard=guard
    )

    # The repaired (marker-ful) answer wins and its citation is verified.
    assert state_update["answer"] == "The policy grants 15 sick days. [1]"
    assert [c.document_title for c in state_update["citations"]] == ["Leave Policy"]
    assert state_update["safety"] == "PASS"
    # Two LLM calls: rewrite + repair.
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_flagged_answer_keeps_draft_when_repair_fails():
    """If the repair adds no markers, the draft is kept but nothing is verified."""
    guard = OutputSafetyPipeline(checks=[CitationCoverageCheck()])
    # The "repair" returns a string with no markers -> discarded.
    llm = ScriptedLLM(["What is the sick leave policy?", "still no markers here"])
    writer = EventCollector()
    service = FakeKnowledgeService(make_result(), answer="The policy grants 15 sick days.")

    state_update = await stream_knowledge_turn(
        service=service, llm=llm, query="sick leave", history=[], writer=writer, guard=guard
    )

    assert state_update["answer"] == "The policy grants 15 sick days."
    assert state_update["citations"] == []
    assert state_update["safety"] == GuardVerdict.FLAGGED_FOR_REVIEW.value


@pytest.mark.asyncio
async def test_pii_redaction_is_applied():
    """A REDACTED verdict serves the sanitized response."""
    from app.safety.output.guards.pii import PIIRedactionCheck

    guard = OutputSafetyPipeline(checks=[PIIRedactionCheck()])
    writer = EventCollector()
    service = FakeKnowledgeService(
        make_result(), answer="Email support at john@example.com for help. [1]"
    )

    state_update = await stream_knowledge_turn(
        service=service,
        llm=FakeLLM("rewritten q"),
        query="who do I contact",
        history=[],
        writer=writer,
        guard=guard,
    )

    assert "john@example.com" not in state_update["answer"]
    assert "[REDACTED]" in state_update["answer"]
    # Redaction happens after streaming: the writer saw the raw token.
    assert "john@example.com" in writer.events[1]["text"]


@pytest.mark.asyncio
async def test_fallback_message():
    """fallback_message distinguishes low-confidence refusal from grounded context."""
    low = KnowledgeTurn(
        original_query="q",
        rewritten_query="q",
        result=make_result(low_confidence=True),
        answer=None,
    )
    assert "couldn't find enough evidence" in fallback_message(low)

    ok = KnowledgeTurn(
        original_query="q",
        rewritten_query="q",
        result=make_result(),
        answer=None,
    )
    assert fallback_message(ok) == "Annual leave accrues at 1.5 days per month. (Leave Policy)"
