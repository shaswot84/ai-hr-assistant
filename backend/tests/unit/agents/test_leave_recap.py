"""Leave Agent: deterministic conversation-recap flow.

"what leave did i apply above?" / "what did we discuss?" are answered from
the thread's OWN history + workflow state (draft, staged confirmation) —
without the model and without tools. The recap must never leak anything
from other conversations or the DB.
"""

from __future__ import annotations

import pytest

from app.agents.leave_agent.agent import handle_turn
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


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


def _provider() -> FakeChatProvider:
    return FakeChatProvider({"reply": "ignored", "action": "reply", "tool": None, "args": {}})


async def _recap(actor, state, message):
    return await handle_turn(
        actor=actor,
        state=state,
        service=LeaveService(None),  # recap never touches the service
        chat_provider=_provider(),
        user_message=message,
    )


@pytest.mark.asyncio
async def test_empty_thread_recap_is_deterministic(employee_context):
    state = _state(employee_context)
    provider = _provider()

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=LeaveService(None),
        chat_provider=provider,
        user_message="what is this chat about?",
    )

    assert provider.calls == 0
    assert "haven't discussed anything" in result.reply


@pytest.mark.asyncio
async def test_recap_includes_history_and_pending_confirmation(employee_context):
    clock = get_clock()
    state = _state(employee_context)
    state.add_turn("employee", "i want causal leave for tomorrow only for one day", clock=clock)
    state.add_turn(
        "agent",
        "Causal Leave would start on Fri, Aug 14, 2026. To which date would you like to end?",
        clock=clock,
    )
    state.stage(
        "submit_leave_request",
        {"leave_type_name": "Causal Leave", "start_date": "2026-08-14", "end_date": "2026-08-14"},
        "Submit a Causal Leave request from 2026-08-14 to 2026-08-14?",
        clock=clock,
    )

    result = await _recap(employee_context, state, "what did i apply above")

    assert "- You: i want causal leave for tomorrow only for one day" in result.reply
    assert "- Assistant: Causal Leave would start on" in result.reply
    assert "Awaiting your confirmation: Submit a Causal Leave" in result.reply


@pytest.mark.asyncio
async def test_recap_mentions_in_progress_draft(employee_context):
    state = _state(employee_context)
    state.draft = DraftRequest(leave_type_name="Causal Leave", start_date=get_clock().today())

    result = await _recap(employee_context, state, "summary of our conversation")

    assert "In progress: Causal Leave starting" in result.reply
    assert "not submitted yet" in result.reply


@pytest.mark.asyncio
async def test_recap_phrasing_variants_all_intercepted(employee_context):
    phrasings = (
        "what did i apply above",
        "what is the above chat about?",
        "what did you do in the chat",
        "summary of our conversation",
        "recap",
        "what did we discuss",
        "what did i ask earlier",
    )
    for phrasing in phrasings:
        state = _state(employee_context)
        provider = _provider()
        result = await handle_turn(
            actor=employee_context,
            state=state,
            service=LeaveService(None),
            chat_provider=provider,
            user_message=phrasing,
        )
        assert provider.calls == 0, phrasing
        assert result.reply.startswith(
            ("Here's what we've discussed", "We haven't discussed anything")
        ), phrasing


@pytest.mark.asyncio
async def test_non_recap_phrasing_goes_to_model(employee_context):
    state = _state(employee_context)
    provider = _provider()

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=LeaveService(None),
        chat_provider=provider,
        user_message="can i go earlier",
    )

    assert provider.calls == 1
    assert result.reply == "ignored"


@pytest.mark.asyncio
async def test_recap_does_not_hijack_draft_cancel(employee_context):
    state = _state(employee_context)
    state.draft = DraftRequest(leave_type_name="Causal Leave", start_date=get_clock().today())
    provider = _provider()

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=LeaveService(None),
        chat_provider=provider,
        user_message="never mind",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert "dropped that draft" in result.reply
