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
