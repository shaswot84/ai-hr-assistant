"""Unit tests for the knowledge agent node (rewrite -> retrieve -> answer).

Uses a fake LLM and a fake KnowledgeService so nothing touches a model
server or a database.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.knowledge_agent.agent import (
    fallback_message,
    rewrite_query,
    run_knowledge_turn,
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
        self.generate_queries: list[str] = []

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        self.retrieve_queries.append(query)
        return self.result

    async def generate_answer(self, query: str, result: KnowledgeResult) -> str | None:
        self.generate_queries.append(query)
        return self.answer


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
async def test_run_knowledge_turn_rewrites_then_retrieves():
    """The node retrieves on the REWRITTEN query, not the raw one."""
    llm = FakeLLM("What is the sick leave policy?")
    service = FakeKnowledgeService(make_result())

    turn = await run_knowledge_turn(
        service=service, llm=llm, query="what about sick leave?", history=[]
    )

    assert service.retrieve_queries == ["What is the sick leave policy?"]
    assert service.generate_queries == ["What is the sick leave policy?"]
    assert turn.answer == "Grounded answer from the policy."
    assert turn.result.confidence == 0.9


@pytest.mark.asyncio
async def test_low_confidence_yields_honest_fallback():
    """Low-confidence retrieval never fabricates an answer — even if the
    service returns one anyway (defense in depth at the node)."""
    from app.agents.supervisor.graph import build_supervisor_graph

    service = FakeKnowledgeService(make_result(low_confidence=True), answer="should not be used")
    graph = build_supervisor_graph(llm=FakeLLM("knowledge"), knowledge_service=service)

    state = await graph.ainvoke({"messages": [], "current_query": "annual leave policy"})

    assert "couldn't find enough evidence" in state["answer"]
    assert "should not be used" not in state["answer"]


@pytest.mark.asyncio
async def test_no_answer_with_evidence_serves_grounded_context():
    """Evidence found but no generated answer -> grounded context fallback."""
    turn = await run_knowledge_turn(
        service=FakeKnowledgeService(make_result(), answer=None),
        llm=None,
        query="annual leave accrual",
        history=[],
    )
    assert turn.answer is None
    assert fallback_message(turn) == "Annual leave accrues at 1.5 days per month. (Leave Policy)"
