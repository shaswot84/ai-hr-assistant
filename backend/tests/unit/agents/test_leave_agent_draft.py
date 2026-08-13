"""Leave Agent: deterministic submit-request flow end to end.

Exercises handle_turn with a real LeaveService (test SQLite DB) and a fake
ChatProvider: relative dates are answered without the model, the draft is
accumulated deterministically, the confirmation is staged by code, and a
"yes" executes the real submission through the existing confirmation gate.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import DraftRequest, LeaveAgentState
from app.capabilities.leave import LeaveService
from app.domain.leave import LeaveRequest
from app.shared.clock import get_clock


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


def _state(actor) -> LeaveAgentState:
    now = get_clock().now()
    return LeaveAgentState(
        session_id="sess-1",
        actor_subject=actor.subject,
        created_at=now,
        updated_at=now,
    )


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


@pytest.mark.asyncio
async def test_relative_start_date_is_answered_without_the_model(
    db, manager_context, employee_context
):
    """"I want annual leave tomorrow" -> deterministic reply with the resolved
    start date and a question for the end date; the model is never called."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="i want to apply for annual leave tomorrow",
    )

    assert provider.calls == 0
    expected = get_clock().today() + timedelta(days=1)
    assert expected.strftime("%a, %b %d, %Y") in result.reply
    assert "To which date would you like to end?" in result.reply
    assert state.draft is not None
    assert state.draft.leave_type_name == "Annual Leave"
    assert state.draft.start_date == expected
    assert state.draft.end_date is None


@pytest.mark.asyncio
async def test_end_only_follow_up_completes_draft_and_stages_confirmation(
    db, manager_context, employee_context
):
    """After a start date is known, "for 3 days" completes the draft and the
    confirmation is staged deterministically (no model call)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    start = get_clock().today() + timedelta(days=1)
    state.set_draft(DraftRequest(leave_type_name="Annual Leave", start_date=start), clock=get_clock())
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="for 3 days",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool == "submit_leave_request"
    assert state.pending_confirmation.args == {
        "leave_type_name": "Annual Leave",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "reason": None,
    }
    assert start.isoformat() in result.reply
    assert (start + timedelta(days=2)).isoformat() in result.reply


@pytest.mark.asyncio
async def test_full_submit_flow_yes_executes_request(
    db, manager_context, employee_context
):
    """Deterministic draft -> staged confirmation -> "yes" submits the real
    request through the confirmation gate."""
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    start = get_clock().today() + timedelta(days=7)
    end = start + timedelta(days=1)
    state.set_draft(DraftRequest(leave_type_name="Annual Leave", start_date=start, end_date=end), clock=get_clock())

    # The draft is complete: interception stages it deterministically.
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}}),
        user_message="for 2 days",
    )
    assert result.tool_called is None
    assert state.pending_confirmation is not None

    # "yes" -> the model confirms with verbatim args; the gate executes.
    pending = state.pending_confirmation
    provider = FakeChatProvider(
        {
            "reply": "Submitting.",
            "action": "call_tool",
            "tool": "submit_leave_request",
            "args": pending.args,
        }
    )
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="yes",
    )

    assert provider.calls == 1
    assert result.tool_called == "submit_leave_request"
    request = db.scalar(select(LeaveRequest))
    assert request is not None
    assert request.leave_type_id == leave_type.leave_type_id
    assert request.start_date == start
    assert request.end_date == end
    assert request.status == "PENDING"


@pytest.mark.asyncio
async def test_cancel_words_drop_the_draft(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    state.set_draft(
        DraftRequest(leave_type_name="Annual Leave", start_date=date(2026, 9, 1)),
        clock=get_clock(),
    )
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="never mind, forget it",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert "dropped" in result.reply


@pytest.mark.asyncio
async def test_complete_draft_is_authoritative_over_model_stage(
    db, manager_context, employee_context
):
    """If the model stages submit with different dates while a complete draft
    exists, the deterministic draft wins (and preflight runs on it)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    start = get_clock().today() + timedelta(days=10)
    end = start + timedelta(days=1)
    state.set_draft(DraftRequest(leave_type_name="Annual Leave", start_date=start, end_date=end), clock=get_clock())
    wrong = {
        "leave_type_name": "Annual Leave",
        "start_date": (start + timedelta(days=30)).isoformat(),
        "end_date": (start + timedelta(days=31)).isoformat(),
        "reason": None,
    }
    provider = FakeChatProvider(
        {
            "reply": "Let me propose that.",
            "action": "stage",
            "tool": "submit_leave_request",
            "args": wrong,
        }
    )

    # "yes" has no resolvable dates -> model flow -> stage reconciliation.
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="yes go ahead",
    )

    assert provider.calls == 1
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.args["start_date"] == start.isoformat()
    assert state.pending_confirmation.args["end_date"] == end.isoformat()
    assert state.draft is None
    assert start.isoformat() in result.reply


@pytest.mark.asyncio
async def test_balance_check_opens_draft_for_request_intent(
    db, manager_context, employee_context
):
    """After a balance check for a request intent, a usable balance opens the
    deterministic draft (single type -> type is pre-filled)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider(
        {
            "reply": "Checking your balance.",
            "action": "call_tool",
            "tool": "get_leave_balance",
            "args": {"leave_type_name": "Annual Leave"},
        }
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="i want to apply for annual leave",
    )

    assert provider.calls == 1
    assert "What dates would you like" in result.reply
    assert state.draft is not None
    assert state.draft.leave_type_name == "Annual Leave"
    assert state.draft.start_date is None


@pytest.mark.asyncio
async def test_no_dates_no_draft_falls_through_to_model(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider(
        {"reply": "What would you like to do?", "action": "reply", "tool": None, "args": {}}
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="what leave types are there",
    )

    assert provider.calls == 1
    assert state.draft is None
    assert result.reply == "What would you like to do?"


@pytest.mark.asyncio
async def test_list_leave_types_for_request_intent_opens_draft_and_asks_type(
    db, manager_context, employee_context
):
    """"apply leave" without a type: the model's list_leave_types reply is
    NOT the end of the turn — the list is followed by the deterministic
    type question, the draft opens, and the next "annual leave" is resolved
    by code (no model call)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave")
    state = _state(employee_context)
    provider = FakeChatProvider(
        {
            "reply": "Let me pull up the leave types.",
            "action": "call_tool",
            "tool": "list_leave_types",
            "args": {},
        }
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="i want to apply for leave",
    )

    assert provider.calls == 1
    assert "Available leave types:" in result.reply
    assert "Annual Leave" in result.reply
    assert "Which leave type would you like to take?" in result.reply
    assert state.draft is not None
    assert state.draft.leave_type_name is None

    pick = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=pick,
        user_message="annual leave",
    )

    assert pick.calls == 0
    assert state.draft.leave_type_name == "Annual Leave"
    assert "From which date would you like to start?" in result.reply


@pytest.mark.asyncio
async def test_list_leave_types_single_type_prefills_draft(
    db, manager_context, employee_context
):
    """Only one leave type exists: the draft is opened pre-filled, and a
    follow-up "tomorrow" resolves deterministically."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Checking.",
                "action": "call_tool",
                "tool": "list_leave_types",
                "args": {},
            }
        ),
        user_message="i want to apply for leave",
    )

    assert state.draft is not None
    assert state.draft.leave_type_name == "Annual Leave"

    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="tomorrow",
    )

    assert provider.calls == 0
    expected = get_clock().today() + timedelta(days=1)
    assert state.draft.start_date == expected
    assert expected.strftime("%a, %b %d, %Y") in result.reply
    assert "To which date would you like to end?" in result.reply