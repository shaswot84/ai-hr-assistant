"""Unit tests for the knowledge agent (rewrite -> retrieve -> stream -> answer).

Uses a fake LLM and a fake KnowledgeService so nothing touches a model
server or a database.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.knowledge_agent.agent import (
    rewrite_query,
    stream_knowledge_turn,
)
from app.knowledge.contracts import Citation, KnowledgeResult
from app.model_gateway.interfaces import LLM


class FakeLLM(LLM):
    """An LLM stub with a canned completion."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


class FakeKnowledgeService:
    """A KnowledgeService stub capturing what the node asks it."""

    def __init__(
        self,
        result: KnowledgeResult,
        answer: str | None = "Grounded answer from the policy.",
    ) -> None:
        self.result = result
        self.answer = answer
        self.retrieve_queries: list[str] = []
        self.stream_queries: list[str] = []

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        self.retrieve_queries.append(query)
        return self.result

    async def stream_answer(self, query: str, result: KnowledgeResult):
        self.stream_queries.append(query)
        if self.answer:
            yield self.answer


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


@pytest.mark.asyncio
async def test_stream_knowledge_turn_rewrites_then_retrieves():
    """The turn retrieves on the REWRITTEN query and streams tokens + state."""
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
    assert writer.events[1]["text"] == "Grounded answer from the policy."

    # The state update carries the final answer + structured facts.
    assert state_update["answer"] == "Grounded answer from the policy."
    assert state_update["agent"] == "knowledge"
    assert state_update["confidence"] == 0.9
    assert len(state_update["citations"]) == 1
    assert state_update["messages"][-1].content == "Grounded answer from the policy."


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
