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
        "is_half_day": False,
        "half_day_period": None,
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


# --- deterministic list flows (requests / leave types) ---------------------


@pytest.mark.asyncio
async def test_list_my_requests_is_deterministic(db, manager_context, employee_context):
    """'show my leave requests' is answered from the REAL data without the
    model — list_my_leave_requests is never left to the model to pick."""
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    today = get_clock().today()
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=6),
        reason=None,
    )
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="show my leave requests",
    )

    assert provider.calls == 0
    assert result.tool_called == "list_my_leave_requests"
    assert "Your leave requests:" in result.reply
    assert "PENDING" in result.reply


@pytest.mark.asyncio
async def test_list_my_requests_empty_reply_is_deterministic(
    db, manager_context, employee_context
):
    """No requests yet -> the deterministic empty reply, no model."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="show my requests",
    )

    assert provider.calls == 0
    assert "You have no leave requests." in result.reply


@pytest.mark.asyncio
async def test_list_requests_does_not_steal_cancel_intent(
    db, manager_context, employee_context
):
    """'cancel my leave request LR-...' is a write intent — the list
    interception must never swallow it into a listing."""
    svc = LeaveService(db)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="cancel my leave request LR-2026-001",
    )

    assert provider.calls == 0
    assert "Your leave requests:" not in result.reply
    assert "Leave request not found." in result.reply  # deterministic cancel preflight


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
async def test_ambiguous_message_does_not_fall_back_to_list_leave_types(
    db, manager_context, employee_context
):
    """The model calling list_leave_types on an ambiguous message (not a
    request start, not a types question) must NOT dump the type list —
    ask what action the employee wants instead."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
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
        user_message="what should i do",
    )

    assert provider.calls == 1
    assert "Available leave types:" not in result.reply
    assert "what would you like to do" in result.reply
    assert state.draft is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "can i get leave for next sunday",
        "i want to take leave for next friday",
        "can i avail leave for next monday",
        "can i book leave for next thursday",
    ],
)
async def test_new_request_intent_words_are_intercepted_without_model(
    db, manager_context, employee_context, message
):
    """'get'/'take'/'avail'/'book' are request-intent words: a message with
    one of them plus a relative date opens the draft deterministically —
    the model is never called and list_leave_types is never dumped."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=message,
    )

    assert provider.calls == 0
    assert state.draft is not None
    assert state.draft.start_date is not None
    assert "Available leave types:" not in result.reply


@pytest.mark.asyncio
async def test_balance_question_does_not_ask_for_dates(
    db, manager_context, employee_context
):
    """A balance QUESTION ('how much can i take') is not a request start —
    the balance is answered deterministically: no date question, no draft,
    no model call, even though 'take'/'get' are request-intent words."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)
    provider = FakeChatProvider(
        {
            "reply": "Checking.",
            "action": "call_tool",
            "tool": "get_leave_balance",
            "args": {},
        }
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="how much annual leave can i take",
    )

    assert provider.calls == 0
    assert "Your leave balance:" in result.reply
    assert "Annual Leave: 20.0 of 20.0 days remaining" in result.reply
    assert "What dates would you like" not in result.reply
    assert state.draft is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "get me leave balance",
        "get my leave",
        "what is my leave balance",
    ],
)
async def test_balance_asks_are_answered_deterministically(
    db, manager_context, employee_context, message
):
    """"get me leave balance" / "get my leave" list the employee's balance
    deterministically — the model is never called and no draft opens, so a
    balance ask can never be answered with a request-start question."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=message,
    )

    assert provider.calls == 0
    assert result.tool_called == "get_leave_balance"
    assert "Your leave balance:" in result.reply
    assert "Annual Leave: 20.0 of 20.0 days remaining" in result.reply
    assert "Which leave type" not in result.reply
    assert state.draft is None


@pytest.mark.asyncio
async def test_specific_type_balance_ask_focuses_on_that_type(
    db, manager_context, employee_context
):
    """"how much sick leave do i have" answers with only the named type's
    balance, not the full grid."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave", default_days=Decimal(10))
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="how much sick leave do i have",
    )

    assert provider.calls == 0
    assert "Sick Leave: 10.0 of 10.0 days remaining" in result.reply
    assert "Annual Leave" not in result.reply


@pytest.mark.asyncio
async def test_can_i_get_leave_asks_type_without_list_dump(
    db, manager_context, employee_context
):
    """"can i get leave?" (request start, no type, no dates) is answered
    with the type question alone — the raw 'Available leave types:' dump is
    suppressed even when the model calls list_leave_types."""
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
        user_message="can i get leave?",
    )

    assert provider.calls == 1
    assert "Available leave types:" not in result.reply
    assert result.reply.startswith("Which leave type would you like to take?")
    assert state.draft is not None
    assert state.draft.leave_type_name is None


@pytest.mark.asyncio
async def test_types_question_list_is_the_answer_without_draft(
    db, manager_context, employee_context
):
    """A direct question about types is answered by the list itself — no
    'which type' follow-up, no draft, and NO model (the list is deterministic)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    _create_leave_type(svc, manager_context, name="Sick Leave")
    state = _state(employee_context)
    provider = FakeChatProvider(
        {
            "reply": "Here are the types.",
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
        user_message="which leave types are there",
    )

    assert provider.calls == 0
    assert "Available leave types:" in result.reply
    assert "Which leave type would you like to take?" not in result.reply
    assert state.draft is None


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
        user_message="i want to know about leave",
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
    assert "Available leave types:" not in result.reply
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


@pytest.mark.asyncio
async def test_half_day_leave_staged_deterministically(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    # Next Tuesday
    today = get_clock().today()
    days_to_tue = ((1 - today.weekday()) % 7) or 7
    tue = today + timedelta(days=days_to_tue)

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"i want to take a half day annual leave on {tue.isoformat()} afternoon",
    )

    assert provider.calls == 0
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool == "submit_leave_request"
    assert state.pending_confirmation.args["is_half_day"] is True
    assert state.pending_confirmation.args["half_day_period"] == "AFTERNOON"
    assert state.pending_confirmation.args["start_date"] == tue.isoformat()
    assert "half-day" in result.reply.lower()


@pytest.mark.asyncio
async def test_holidays_interception_in_leave_agent(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    svc.create_company_holiday(
        manager_context,
        name="Winter Solstice",
        holiday_date=date(2026, 12, 21),
    )
    state = _state(employee_context)

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="what are the upcoming company holidays?",
    )

    assert provider.calls == 0
    assert "Winter Solstice" in result.reply
    assert result.tool_called == "list_company_holidays"
    assert result.ui_widget is not None
    assert result.ui_widget["type"] == "company_holidays"


@pytest.mark.asyncio
async def test_team_out_of_office_interception_in_leave_agent(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    state = _state(employee_context)

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="who is out of office today?",
    )

    assert provider.calls == 0
    assert result.tool_called == "get_team_out_of_office"
    assert result.ui_widget is not None
    assert result.ui_widget["type"] == "team_out_of_office"


@pytest.mark.asyncio
async def test_single_day_leave_staged_in_one_turn(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    # Next Tuesday
    today = get_clock().today()
    days_to_tue = ((1 - today.weekday()) % 7) or 7
    tue = today + timedelta(days=days_to_tue)

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"i want to apply for 1 day annual leave on {tue.isoformat()}",
    )

    assert provider.calls == 0
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool == "submit_leave_request"
    assert state.pending_confirmation.args["start_date"] == tue.isoformat()
    assert state.pending_confirmation.args["end_date"] == tue.isoformat()
    assert "1 working day" in result.reply.lower() or "1 day" in result.reply.lower() or tue.isoformat() in result.reply


@pytest.mark.asyncio
async def test_single_day_leave_follow_up_with_same_day(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    today = get_clock().today()
    days_to_tue = ((1 - today.weekday()) % 7) or 7
    tue = today + timedelta(days=days_to_tue)

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    # Turn 1: Start date only
    res1 = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"i want annual leave on {tue.isoformat()}",
    )
    assert provider.calls == 0
    assert state.draft is not None
    assert state.draft.start_date == tue
    assert state.draft.end_date is None

    # Turn 2: Follow up with "same day" or the same date
    res2 = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="same day",
    )
    assert provider.calls == 0
    assert state.pending_confirmation.args["start_date"] == tue.isoformat()
    assert state.pending_confirmation.args["end_date"] == tue.isoformat()


@pytest.mark.asyncio
async def test_agent_mentions_custom_holiday_when_leave_falls_on_it(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    today = get_clock().today()
    days_to_wed = ((2 - today.weekday()) % 7) or 7
    wed = today + timedelta(days=days_to_wed)

    # Create a custom holiday on that Wednesday
    svc.create_company_holiday(
        manager_context,
        name="Team Offsite Day",
        holiday_date=wed,
        is_recurring_yearly=False,
    )

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"i want to take 1 day annual leave on {wed.isoformat()}",
    )

    assert provider.calls == 0
    assert "Team Offsite Day" in result.reply
    assert "custom company holiday created by the company" in result.reply
    assert "0 leave days" in result.reply or "no leave" in result.reply.lower()


@pytest.mark.asyncio
async def test_agent_includes_custom_holiday_in_range_confirmation(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    state = _state(employee_context)

    today = get_clock().today()
    days_to_next_mon = ((0 - today.weekday()) % 7) or 7
    mon = today + timedelta(days=days_to_next_mon)
    fri = mon + timedelta(days=4)
    wed = mon + timedelta(days=2)

    # Create custom holiday on Wednesday
    svc.create_company_holiday(
        manager_context,
        name="Founder Appreciation Day",
        holiday_date=wed,
        is_recurring_yearly=False,
    )

    provider = FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"i want to take annual leave from {mon.isoformat()} to {fri.isoformat()}",
    )

    assert provider.calls == 0
    assert state.pending_confirmation is not None
    assert "Founder Appreciation Day" in result.reply
    assert "custom company holiday created by the company" in result.reply
    assert "4 working days" in result.reply