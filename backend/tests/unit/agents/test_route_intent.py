"""Unit tests for the routing logic (LLM classification + keyword fallback).

These run without any model server: routing is the one piece of the
supervisor that must be deterministic enough to test in isolation.
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.supervisor.route_intent import heuristic_route, route_intent
from app.model_gateway.interfaces import LLM


class FakeLLM(LLM):
    """An LLM stub that returns a canned completion."""

    model = "fake"

    def __init__(self, response: str) -> None:
        self.response = response
        self.calls: list[tuple[str, str]] = []

    async def complete(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        return self.response


def test_heuristic_leave_keywords():
    """Leave keywords route to leave — including inside longer questions."""
    assert heuristic_route("how many days of annual leave do I have") == "leave"
    assert heuristic_route("my sick leave balance") == "leave"
    assert heuristic_route("book time off next week") == "leave"


def test_heuristic_recruitment_keywords():
    """Recruitment keywords route to recruitment."""
    assert heuristic_route("how do I apply for the data analyst vacancy") == "recruitment"
    assert heuristic_route("is there an interview coming up") == "recruitment"


def test_heuristic_leave_wins_over_recruitment():
    """'apply for leave' is a leave question, not a recruitment one."""
    assert heuristic_route("how do I apply for leave") == "leave"


def test_heuristic_defaults_to_knowledge():
    """Anything without a keyword defaults to the knowledge base."""
    assert heuristic_route("what is the dress code") == "knowledge"
    assert heuristic_route("how does health insurance work") == "knowledge"


def test_heuristic_leave_policy_routes_to_knowledge():
    """Leave POLICY questions go to the knowledge agent (RAG), not the
    transactional leave agent — the leave agent has no retrieval path and
    cannot answer them."""
    assert heuristic_route("what is the annual leave policy") == "knowledge"
    assert heuristic_route("annual leave accrual rate") == "knowledge"
    assert heuristic_route("how does sick leave accrual work") == "knowledge"
    assert heuristic_route("am I entitled to casual leave") == "knowledge"


def test_heuristic_leave_transactions_still_route_to_leave():
    """Transactional leave asks stay on the leave agent even when they
    contain policy-adjacent words."""
    assert heuristic_route("my annual leave balance") == "leave"
    assert heuristic_route("how many days of annual leave do I have") == "leave"
    assert heuristic_route("request annual leave for tomorrow") == "leave"


def test_heuristic_definition_questions_route_to_knowledge():
    """Definition/explanation questions about leave types are knowledge
    questions — the KB defines them, the transactional leave agent can't."""
    assert heuristic_route("what is annual leave") == "knowledge"
    assert heuristic_route("what's sick leave") == "knowledge"
    assert heuristic_route("what are casual leave days") == "knowledge"
    assert heuristic_route("how does annual leave work") == "knowledge"
    assert heuristic_route("meaning of unpaid leave") == "knowledge"


def test_heuristic_definition_questions_with_transaction_framing_stay_leave():
    """Personal/transactional framing keeps a "what is..." message on leave:
    "what is MY balance" is a balance ask, not a definition question."""
    assert heuristic_route("what is my annual leave balance") == "leave"
    assert heuristic_route("what is left of my annual leave") == "leave"
    assert heuristic_route("what is a leave request") == "leave"
    assert heuristic_route("how do i apply for leave") == "leave"


@pytest.mark.asyncio
async def test_route_intent_overrides_llm_misclassification_to_knowledge():
    """A clearly knowledge-framed leave question is re-routed to knowledge
    even when the LLM (wrongly) says leave — the deterministic check and the
    LLM must agree on the knowledge/leave boundary."""
    llm = FakeLLM("leave")
    assert await route_intent(llm, "what is the annual leave policy", []) == "knowledge"
    assert await route_intent(llm, "what is annual leave", []) == "knowledge"
    assert await route_intent(llm, "how does sick leave accrual work", []) == "knowledge"


@pytest.mark.asyncio
async def test_route_intent_overrides_llm_misclassification_to_leave():
    """The reverse direction: a clearly TRANSACTIONAL leave ask is re-routed
    to the leave agent even when the LLM (wrongly) says knowledge — it has the
    tools (balance / requests / types) the knowledge agent doesn't."""
    llm = FakeLLM("knowledge")
    assert await route_intent(llm, "show my leave requests", []) == "leave"
    assert await route_intent(llm, "which leave types can i request", []) == "leave"
    assert await route_intent(llm, "my leave balance", []) == "leave"
    assert await route_intent(llm, "how do i cancel my leave request", []) == "leave"


@pytest.mark.asyncio
async def test_route_intent_reverse_override_never_steals_policy_questions():
    """Policy/definition wording blocks the reverse override — a knowledge
    question about leave policy stays on the knowledge agent even when the
    LLM and the transactional wording could both pull it toward leave."""
    llm = FakeLLM("knowledge")
    assert await route_intent(llm, "what is the annual leave policy", []) == "knowledge"
    assert await route_intent(llm, "show me the leave policy", []) == "knowledge"
    assert await route_intent(llm, "how does sick leave accrual work", []) == "knowledge"


@pytest.mark.asyncio
async def test_route_intent_keeps_transactional_leave_with_llm():
    """Transactional leave stays on leave even with policy-adjacent words."""
    llm = FakeLLM("leave")
    assert await route_intent(llm, "my annual leave balance", []) == "leave"
    assert await route_intent(llm, "request annual leave for tomorrow", []) == "leave"


def test_routing_prompt_pins_knowledge_vs_leave_boundary():
    """The routing prompt keeps the knowledge/leave boundary explicit so the
    LLM path agrees with the deterministic heuristic — a prompt edit that
    drops these examples fails loudly here."""
    from app.agents.supervisor.prompts import ROUTING_SYSTEM

    assert "what is the annual leave policy?" in ROUTING_SYSTEM
    assert "what is annual leave?" in ROUTING_SYSTEM
    assert "leave ACTIONS" in ROUTING_SYSTEM
    assert "what is my annual leave balance?" in ROUTING_SYSTEM


@pytest.mark.asyncio
async def test_route_intent_uses_llm_response():
    """A clean single-word LLM reply is used as-is."""
    llm = FakeLLM("leave")
    assert await route_intent(llm, "tell me about my balance", []) == "leave"


@pytest.mark.asyncio
async def test_route_intent_tolerates_noisy_reply():
    """The model wrapping its answer in a sentence still parses."""
    llm = FakeLLM("I think this is about recruitment.")
    assert await route_intent(llm, "open positions", []) == "recruitment"


@pytest.mark.asyncio
async def test_route_intent_falls_back_on_garbage():
    """An unparseable reply falls back to keyword routing."""
    llm = FakeLLM("hmm, not sure what you mean")
    assert await route_intent(llm, "my annual leave balance", []) == "leave"


@pytest.mark.asyncio
async def test_route_intent_falls_back_when_llm_raises():
    """A failing LLM never breaks routing — heuristics take over."""

    class BrokenLLM(FakeLLM):
        async def complete(self, system: str, user: str) -> str:
            raise RuntimeError("ollama down")

    assert await route_intent(BrokenLLM("ignored"), "apply for a job", []) == "recruitment"


@pytest.mark.asyncio
async def test_route_intent_without_llm_uses_heuristics():
    """With no LLM configured, routing is purely keyword-based."""
    assert await route_intent(None, "what is the annual leave policy", []) == "knowledge"
    assert await route_intent(None, "open vacancies", []) == "recruitment"
    assert await route_intent(None, "what is the onboarding process", []) == "knowledge"


@pytest.mark.asyncio
async def test_routing_prompt_includes_history():
    """The routing prompt carries conversation context for follow-ups."""
    llm = FakeLLM("knowledge")
    history = [
        HumanMessage(content="How much annual leave do I have?"),
        AIMessage(content="You have 15 days remaining."),
    ]
    await route_intent(llm, "what about sick leave?", history)

    _, user_prompt = llm.calls[0]
    assert "User: How much annual leave do I have?" in user_prompt
    assert "Assistant: You have 15 days remaining." in user_prompt
    assert "what about sick leave?" in user_prompt
