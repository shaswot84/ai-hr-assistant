"""Leave Agent intent predicates + the phrasings they must catch.

The deterministic interceptions are keyword-driven by design; these tests
pin the boundary so a common phrasing that escapes the word lists (and would
fall to the model) fails loudly here.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest

from app.agents.leave_agent.agent import (
    _is_balance_ask,
    _is_request_intent,
    handle_turn,
)
from app.agents.leave_agent.state import DraftRequest, LeaveAgentState
from app.capabilities.leave import LeaveService
from app.shared.clock import get_clock


def _state(actor) -> LeaveAgentState:
    now = get_clock().now()
    return LeaveAgentState(
        session_id="sess-1",
        actor_subject=actor.subject,
        created_at=now,
        updated_at=now,
    )


def _create_leave_type(svc, actor, *, name="Annual Leave", default_days=Decimal(20)):
    return svc.create_leave_type(
        actor,
        leave_name=name,
        description="Planned time off.",
        default_days=default_days,
        requires_approval=True,
        is_paid=True,
        max_consecutive_days=None,
    )


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


# --- balance-ask predicate ------------------------------------------------


def test_balance_ask_recognizes_possessive_leave_phrasing():
    """'show my pto' / 'my time off' are balance asks (previously they fell
    to the model); request wording keeps them requests."""
    assert _is_balance_ask("show my pto")
    assert _is_balance_ask("my time off")
    assert _is_balance_ask("what do i have left in my vacation")
    assert _is_balance_ask("get my leave")
    assert _is_balance_ask("what is my leave balance")
    assert not _is_balance_ask("can i book my time off")
    assert not _is_balance_ask("i want to use my annual leave")
    assert not _is_balance_ask("show my leave requests")
    assert not _is_balance_ask("show me someone else's balance")
    assert not _is_balance_ask("can i get leave for next sunday")


# --- request-intent predicate ---------------------------------------------


def test_request_intent_recognizes_common_phrasing():
    """'i'd like', 'can i have', and 'go on leave' start requests — the
    model is never asked to understand them."""
    assert _is_request_intent("i'd like annual leave on friday")
    assert _is_request_intent("id like leave next week")
    assert _is_request_intent("can i have leave tomorrow")
    assert _is_request_intent("i'm going on leave next month")
    assert _is_request_intent("i want to go on leave")
    assert _is_request_intent("can i get leave for next sunday")
    assert not _is_request_intent("is annual leave available")
    assert not _is_request_intent("show my leave balance")
    assert not _is_request_intent("what is the annual leave policy")


# --- end-to-end flows through handle_turn ---------------------------------


@pytest.mark.asyncio
async def test_id_like_annual_leave_on_friday_is_deterministic(
    db, manager_context, employee_context
):
    """'i'd like annual leave on friday' starts the deterministic draft flow
    (day resolved by code, model never called)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="i'd like annual leave on friday",
    )

    assert provider.calls == 0
    assert state.draft is not None
    assert state.draft.leave_type_name == "Annual Leave"
    assert "To which date would you like to end?" in result.reply


@pytest.mark.asyncio
async def test_my_pto_is_deterministic_balance(db, manager_context, employee_context):
    """'show my pto' answers the real balance without the model — a phrase
    that previously escaped the balance word list."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="PTO", default_days=Decimal(10))
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="show my pto",
    )

    assert provider.calls == 0
    assert result.tool_called == "get_leave_balance"
    assert "Your leave balance:" in result.reply
    assert "PTO: 10.0 of 10.0 days remaining" in result.reply
    assert state.draft is None


@pytest.mark.asyncio
async def test_on_second_thought_drops_draft(db, manager_context, employee_context):
    """Mid-draft 'on second thought' clears the draft deterministically."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    state.draft = DraftRequest(
        leave_type_name="Annual Leave",
        start_date=get_clock().today(),
        end_date=get_clock().today() + timedelta(days=1),
    )
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="on second thought, forget it",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert "dropped" in result.reply
