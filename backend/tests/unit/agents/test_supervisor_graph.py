"""End-to-end unit tests for the supervisor graph.

Builds the real LangGraph with fake LLM + fake knowledge service, and asserts
routing dispatch, node outputs, and the state the chat layer will persist.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import HumanMessage

from app.agents.supervisor.graph import build_supervisor_graph
from app.knowledge.contracts import Citation, KnowledgeResult
from app.model_gateway.interfaces import LLM


class FakeLLM(LLM):
    """An LLM stub with a canned completion (same reply for every call)."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response

    async def complete(self, system: str, user: str) -> str:
        return self.response


class FakeKnowledgeService:
    """A KnowledgeService stub returning a fixed retrieval result."""

    def __init__(self, result: KnowledgeResult, answer: str | None = "A grounded answer.") -> None:
        self.result = result
        self.answer = answer

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        return self.result

    async def generate_answer(self, query: str, result: KnowledgeResult) -> str | None:
        return self.answer


def make_result() -> KnowledgeResult:
    """A confident retrieval result with one citation."""
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
        citations=[citation],
        confidence=0.92,
        chunks=[],
        low_confidence=False,
    )


@pytest.mark.asyncio
async def test_routes_to_knowledge_and_answers():
    """A knowledge question runs the knowledge node and returns the answer."""
    graph = build_supervisor_graph(
        llm=FakeLLM("knowledge"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke({"messages": [], "current_query": "What is the annual leave policy?"})

    assert state["agent"] == "knowledge"
    assert state["route"] == "knowledge"
    assert state["answer"] == "A grounded answer."
    assert state["confidence"] == 0.92
    assert len(state["citations"]) == 1
    assert state["citations"][0].document_title == "Leave Policy"
    assert state["messages"][-1].type == "ai"
    assert state["messages"][-1].content == "A grounded answer."
    assert state["knowledge_result"] is not None


@pytest.mark.asyncio
async def test_routes_to_leave_stub():
    """A leave question hits the leave stub node until the real agent lands."""
    graph = build_supervisor_graph(
        llm=FakeLLM("leave"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke({"messages": [], "current_query": "my leave balance"})

    assert state["agent"] == "leave"
    assert "Leave" in state["answer"]
    assert "chat" in state["answer"]
    assert state["citations"] == []
    assert state["knowledge_result"] is None


@pytest.mark.asyncio
async def test_routes_to_recruitment_stub():
    """A recruitment question hits the recruitment stub node."""
    graph = build_supervisor_graph(
        llm=FakeLLM("recruitment"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke({"messages": [], "current_query": "how do I apply?"})

    assert state["agent"] == "recruitment"
    assert "Recruitment" in state["answer"]
    assert "Careers" in state["answer"]


@pytest.mark.asyncio
async def test_routes_to_clarify():
    """An ambiguous message routes to the clarify node, which asks for specifics."""
    graph = build_supervisor_graph(
        llm=FakeLLM("clarify"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke({"messages": [], "current_query": "hi"})

    assert state["agent"] == "clarify"
    assert "Could you clarify" in state["answer"]


@pytest.mark.asyncio
async def test_no_llm_routes_by_heuristics():
    """Without an LLM, routing falls back to keywords and the graph still works."""
    graph = build_supervisor_graph(llm=None, knowledge_service=FakeKnowledgeService(make_result()))

    # Keyword "annual leave" routes to leave even with no LLM.
    state = await graph.ainvoke({"messages": [], "current_query": "what is annual leave"})
    assert state["agent"] == "leave"

    # A knowledge question falls through to the knowledge node.
    state = await graph.ainvoke({"messages": [], "current_query": "what is the dress code"})
    assert state["agent"] == "knowledge"


@pytest.mark.asyncio
async def test_no_llm_serves_grounded_context_when_evidence_found():
    """No LLM + evidence -> the knowledge node serves the grounded context."""
    graph = build_supervisor_graph(
        llm=None, knowledge_service=FakeKnowledgeService(make_result(), answer=None)
    )

    state = await graph.ainvoke({"messages": [], "current_query": "dress code policy"})

    assert state["agent"] == "knowledge"
    assert state["answer"] == "Annual leave accrues at 1.5 days per month. (Leave Policy)"


@pytest.mark.asyncio
async def test_history_is_preserved_and_passed_to_routing():
    """Prior turns ride through the graph for context-aware routing."""
    llm = FakeLLM("knowledge")
    graph = build_supervisor_graph(llm=llm, knowledge_service=FakeKnowledgeService(make_result()))
    history = [HumanMessage(content="How much annual leave do I have?")]

    state = await graph.ainvoke(
        {"messages": history, "current_query": "what about sick leave?"}
    )

    # The graph keeps prior turns and appends the assistant reply.
    assert [m.content for m in state["messages"]] == [
        "How much annual leave do I have?",
        "A grounded answer.",
    ]
