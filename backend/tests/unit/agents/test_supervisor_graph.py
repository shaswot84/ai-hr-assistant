"""End-to-end unit tests for the supervisor graph.

Builds the real LangGraph with fake LLM + fake knowledge service, and asserts
routing dispatch, node outputs, and the state the chat layer will persist.
"""

from __future__ import annotations

import uuid

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.supervisor.graph import build_supervisor_graph
from app.contracts.auth import UserContext
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

    def __init__(self, result: KnowledgeResult, answer: str | None = "A grounded answer. [1]") -> None:
        self.result = result
        self.answer = answer

    async def retrieve(self, query: str, **kwargs) -> KnowledgeResult:
        return self.result

    async def generate_answer(self, query: str, result: KnowledgeResult, *, history=None) -> str | None:
        return self.answer

    async def stream_answer(self, query: str, result: KnowledgeResult, *, history=None):
        if self.answer:
            yield self.answer


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
    assert state["answer"] == "A grounded answer. [1]"
    assert state["confidence"] == 0.92
    assert state["safety"] == "PASS"
    assert len(state["citations"]) == 1
    assert state["citations"][0].document_title == "Leave Policy"
    assert state["messages"][-1].type == "ai"
    assert state["messages"][-1].content == "A grounded answer. [1]"
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
async def test_routes_to_recruitment_node():
    """A recruitment question runs the deterministic recruitment node (no more stub)."""
    graph = build_supervisor_graph(
        llm=FakeLLM("recruitment"),
        knowledge_service=FakeKnowledgeService(make_result()),
        recruitment_service=_FakeRecruitmentService(),
    )

    state = await graph.ainvoke({"messages": [], "current_query": "how do I apply?"})

    assert state["agent"] == "recruitment"
    assert "Careers" in state["answer"]
    assert state["citations"] == []
    assert state["knowledge_result"] is None
    assert state["confidence"] == 0.0


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

    # A definition question about a leave type routes to knowledge — the KB
    # answers it, the transactional leave agent can't.
    state = await graph.ainvoke({"messages": [], "current_query": "what is annual leave"})
    assert state["agent"] == "knowledge"

    # A transactional leave ask routes to leave even with no LLM.
    state = await graph.ainvoke({"messages": [], "current_query": "my annual leave balance"})
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


class RewritingFakeLLM(FakeLLM):
    """Route token on the first call (routing), rewritten query on the second."""

    def __init__(self, route: str, rewritten: str) -> None:
        super().__init__(route)
        self.route = route
        self.rewritten = rewritten
        self._calls = 0

    async def complete(self, system: str, user: str) -> str:
        self._calls += 1
        return self.route if self._calls == 1 else self.rewritten


@pytest.mark.asyncio
async def test_knowledge_node_streams_events():
    """astream surfaces retrieval + token custom events from the knowledge node."""
    graph = build_supervisor_graph(
        llm=RewritingFakeLLM("knowledge", "annual leave policy?"),
        knowledge_service=FakeKnowledgeService(make_result()),
    )

    events = [
        chunk
        async for mode, chunk in graph.astream(
            {"messages": [], "current_query": "annual leave policy"},
            stream_mode=["custom", "updates"],
        )
        if mode == "custom"
    ]

    types = [e["type"] for e in events]
    assert types[0] == "retrieval"
    assert types[1:] == ["token"]
    assert events[0]["rewritten_query"] == "annual leave policy?"
    assert events[1]["text"] == "A grounded answer. [1]"


@pytest.mark.asyncio
async def test_leave_node_streams_message_event():
    """Stub nodes stream a single message event instead of tokens."""
    graph = build_supervisor_graph(
        llm=FakeLLM("leave"), knowledge_service=FakeKnowledgeService(make_result())
    )

    events = [
        chunk
        async for mode, chunk in graph.astream(
            {"messages": [], "current_query": "my leave balance"},
            stream_mode=["custom", "updates"],
        )
        if mode == "custom"
    ]

    assert [e["type"] for e in events] == ["message"]
    assert "Leave" in events[0]["text"]


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
        "A grounded answer. [1]",
    ]


@pytest.mark.asyncio
async def test_history_question_routes_to_recap_node():
    """A generic "what is this chat about?" is pre-routed to the recap node —
    even when the LLM would have said clarify."""
    graph = build_supervisor_graph(
        llm=FakeLLM("We discussed the annual leave policy and your leave balance."),
        knowledge_service=FakeKnowledgeService(make_result()),
    )
    history = [
        HumanMessage(content="what is the annual leave policy?"),
        AIMessage(content="Annual leave accrues at 1.5 days per month. [1]"),
    ]

    state = await graph.ainvoke(
        {"messages": history, "current_query": "what is this chat about?"}
    )

    assert state["agent"] == "recap"
    assert state["route"] == "recap"
    assert state["answer"] == "We discussed the annual leave policy and your leave balance."
    assert state["messages"][-1].content == state["answer"]
    assert state["citations"] == []


@pytest.mark.asyncio
async def test_recap_without_llm_serves_transcript():
    """No LLM -> the recap node serves the transcript itself (still answers)."""
    graph = build_supervisor_graph(llm=None, knowledge_service=FakeKnowledgeService(make_result()))
    history = [
        HumanMessage(content="How much annual leave do I have?"),
        AIMessage(content="You have 20 days."),
    ]

    state = await graph.ainvoke(
        {"messages": history, "current_query": "what did we discuss"}
    )

    assert state["agent"] == "recap"
    assert state["answer"].startswith("Here's what we discussed")
    assert "How much annual leave do I have?" in state["answer"]


@pytest.mark.asyncio
async def test_leave_scoped_history_question_routes_to_leave():
    """"what leave did i apply above" is leave-scoped: it goes to the leave
    node (whose own deterministic interception answers it), not to recap."""
    graph = build_supervisor_graph(
        llm=FakeLLM("clarify"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke({"messages": [], "current_query": "what leave did i apply above"})

    assert state["route"] == "leave"
    assert state["agent"] == "leave"


@pytest.mark.asyncio
async def test_history_question_does_not_override_cancel_intent():
    """A cancel intent mentioning "above" still routes by normal routing —
    the recap pre-check never swallows write intents."""
    graph = build_supervisor_graph(
        llm=FakeLLM("leave"), knowledge_service=FakeKnowledgeService(make_result())
    )

    state = await graph.ainvoke(
        {"messages": [], "current_query": "cancel the leave request from above"}
    )

    assert state["route"] == "leave"


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


def _leave_actor() -> UserContext:
    return UserContext(
        subject="emp-1",
        email="emp@example.com",
        display_name="Employee",
        coarse_role="EMPLOYEE",
    )


class _FakeLeaveType:
    def __init__(self, name: str) -> None:
        self.leave_name = name


class _FakeRecruitmentService:
    """An empty RecruitmentService stub — enough for the apply deferral path."""

    def list_vacancies(self, actor=None):
        return []

    def list_all_applications(self, actor):
        return []

    def list_vacancy_applications(self, actor, vacancy_id):
        return []

    def list_my_applications(self, actor):
        return []


class _FakeLeaveService:
    """A LeaveService stub for the knowledge node's balance enrichment."""

    def list_leave_types(self):
        return [_FakeLeaveType("Sick Leave")]

    def list_my_balance(self, actor, year=None):
        return [
            {
                "leave_type": _FakeLeaveType("Sick Leave"),
                "year": 2026,
                "allocated_days": "10",
                "used_days": "5.5",
                "remaining_days": "4.5",
            }
        ]


@pytest.mark.asyncio
async def test_knowledge_node_appends_balance_when_wired():
    """When the chat layer wires knowledge_actor + knowledge_leave_service,
    a balance-relevant employee question routes to knowledge AND gets the
    employee's real balance appended to the policy answer."""
    graph = build_supervisor_graph(
        llm=FakeLLM("knowledge"),
        knowledge_service=FakeKnowledgeService(make_result()),
        knowledge_actor=_leave_actor(),
        knowledge_leave_service=_FakeLeaveService(),
    )

    state = await graph.ainvoke(
        {"messages": [], "current_query": "how many sick days do i get"}
    )

    assert state["agent"] == "knowledge"
    assert state["answer"] == (
        "A grounded answer. [1]\n\n"
        "Your leave balance:\nSick Leave: 4.5 of 10 days remaining"
    )
    assert len(state["citations"]) == 1


@pytest.mark.asyncio
async def test_wired_leave_node_runs_real_agent():
    """When the chat layer wires leave deps, the graph runs the real agent.

    The message must be one the leave agent's deterministic interceptions
    don't swallow: "my leave balance" is answered from the real balance and
    "show my leave requests" from the real request list, both without the
    model — so the dispatch loop is exercised through a neutral conversational
    turn ("what can you help with") that reaches the provider.
    """
    from app.agents.leave_agent.state import SessionStore

    provider = FakeChatProvider(
        {"reply": "I can help with leave balance, requests, and more.", "action": "reply", "tool": None, "args": {}}
    )
    graph = build_supervisor_graph(
        llm=FakeLLM("leave"),
        knowledge_service=FakeKnowledgeService(make_result()),
        leave_actor=_leave_actor(),
        leave_store=SessionStore(),
        leave_chat_provider=provider,
    )

    state = await graph.ainvoke(
        {"messages": [], "current_query": "what can you help with", "conversation_id": str(uuid.uuid4())}
    )

    assert provider.calls == 1
    assert state["agent"] == "leave"
    assert state["answer"] == "I can help with leave balance, requests, and more."
    assert state["messages"][-1].content == state["answer"]
    assert state["citations"] == []


@pytest.mark.asyncio
async def test_unwired_leave_node_stays_stub():
    """Without leave deps the node is the honest stub (provider never called)."""
    provider = FakeChatProvider(
        {"reply": "should not be used", "action": "reply", "tool": None, "args": {}}
    )
    graph = build_supervisor_graph(
        llm=FakeLLM("leave"),
        knowledge_service=FakeKnowledgeService(make_result()),
    )

    state = await graph.ainvoke({"messages": [], "current_query": "my leave balance"})

    assert "Leave" in state["answer"]
    assert "chat" in state["answer"]
    assert provider.calls == 0
