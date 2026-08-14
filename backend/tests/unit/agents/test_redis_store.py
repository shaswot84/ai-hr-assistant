"""Redis-backed leave session store: cross-process safety and full-state
round trips, tested hermetically with fakeredis.

The store replaces the in-memory per-process SessionStore when REDIS_URL is
configured. The key properties tested here: (1) the full working slice
(history + draft + pending) round-trips so a turn landing on a different
worker sees the same conversation memory, and (2) the execution claim is a
real cross-process lock — two workers can never both execute the same
staged confirmation.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import fakeredis
import pytest
from sqlalchemy import select

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import (
    DraftRequest,
    LeaveAgentState,
    RedisSessionStore,
)
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.domain.leave import LeaveRequest
from app.shared.clock import get_clock


def _employee() -> UserContext:
    return UserContext(subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE")


def _store() -> RedisSessionStore:
    return RedisSessionStore(client=fakeredis.FakeRedis(decode_responses=True))


def _state(actor, session_id: str = "sess-1") -> LeaveAgentState:
    now = get_clock().now()
    return LeaveAgentState(
        session_id=session_id,
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


def test_full_session_round_trip_preserves_history_draft_pending():
    """The working slice Redis stores is the FULL state — a turn landing on a
    different worker must see the same conversation memory."""
    store = _store()
    actor = _employee()
    state = _state(actor)
    state.add_turn("employee", "i want annual leave", clock=get_clock())
    state.add_turn("agent", "Which dates?", clock=get_clock())
    state.draft = DraftRequest(leave_type_name="Annual Leave")
    state.stage(
        "submit_leave_request",
        {"leave_type_name": "Annual Leave"},
        "Submit Annual Leave?",
        clock=get_clock(),
    )

    store.put(state)
    restored = store.get("sess-1", actor)

    assert restored is not None
    assert [t.as_dict() for t in restored.history] == [
        {"role": "employee", "content": "i want annual leave"},
        {"role": "agent", "content": "Which dates?"},
    ]
    assert restored.draft.leave_type_name == "Annual Leave"
    assert restored.pending_confirmation.tool == "submit_leave_request"
    assert restored.pending_confirmation.args == {"leave_type_name": "Annual Leave"}


def test_get_rejects_identity_mismatch():
    """A client-supplied session id is not a trusted identity boundary."""
    store = _store()
    actor = _employee()
    store.put(_state(actor))
    other = UserContext(
        subject="emp-2", email="o@x.com", display_name="O", coarse_role="EMPLOYEE"
    )
    assert store.get("sess-1", other) is None


def test_get_or_create_starts_fresh_and_round_trips():
    store = _store()
    actor = _employee()
    fresh = store.get_or_create("sess-9", actor)
    assert fresh.history == []
    assert fresh.actor_subject == actor.subject
    assert store.get("sess-9", actor) is not None


def test_session_keys_get_ttl():
    """Redis expires the working slice after the session TTL."""
    store = _store()
    store.put(_state(_employee()))
    assert store._client.ttl(store._session_key("sess-1")) > 0


def test_execution_claim_is_atomic_across_materialized_states():
    """Two worker processes each have their OWN store over the same Redis;
    only one may hold the execution claim at a time, and a worker can never
    release another worker's claim."""
    server = fakeredis.FakeRedis(decode_responses=True)
    store_a = RedisSessionStore(client=server)  # worker A's process store
    store_b = RedisSessionStore(client=server)  # worker B's process store
    actor = _employee()
    first = _state(actor)
    second = _state(actor)  # what worker B would materialize

    first.bind_claim(
        lambda: store_a.begin_execution("sess-1"),
        lambda: store_a.end_execution("sess-1"),
    )
    second.bind_claim(
        lambda: store_b.begin_execution("sess-1"),
        lambda: store_b.end_execution("sess-1"),
    )

    assert first.begin_execution() is True
    assert second.begin_execution() is False  # cross-process claim is held
    second.end_execution(clock=get_clock())  # worker B cannot release A's claim
    assert first.begin_execution() is False  # still held
    first.end_execution(clock=get_clock())  # worker A releases its own
    assert second.begin_execution() is True  # released: a new turn may proceed


@pytest.mark.asyncio
async def test_redis_claim_blocks_concurrent_confirmation(
    db, manager_context, employee_context
):
    """While another worker holds the claim, a confirmed "yes" is refused and
    nothing is written — the confirmation gate is cross-process, not just a
    per-process flag."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    start = get_clock().today() + timedelta(days=7)
    end = start + timedelta(days=1)

    actor = employee_context
    state = _state(actor)
    state.set_draft(
        DraftRequest(leave_type_name="Annual Leave", start_date=start, end_date=end),
        clock=get_clock(),
    )
    # The complete draft is staged deterministically (no model call).
    await handle_turn(
        actor=actor,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}}),
        user_message="for 2 days",
    )
    assert state.pending_confirmation is not None
    pending = state.pending_confirmation

    store = _store()
    state.bind_claim(
        lambda: store.begin_execution(state.session_id),
        lambda: store.end_execution(state.session_id),
    )

    # Another worker (or a retried request) is mid-turn: the claim is held.
    assert store.begin_execution(state.session_id) is True

    result = await handle_turn(
        actor=actor,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Submitting.",
                "action": "call_tool",
                "tool": "submit_leave_request",
                "args": pending.args,
            }
        ),
        user_message="yes",
    )

    assert result.tool_called is None
    assert "already processing" in result.reply
    assert db.scalar(select(LeaveRequest)) is None  # nothing executed

    # Once the claim is released, the same staged action executes normally.
    store.end_execution(state.session_id)
    result = await handle_turn(
        actor=actor,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Submitting.",
                "action": "call_tool",
                "tool": "submit_leave_request",
                "args": pending.args,
            }
        ),
        user_message="yes",
    )
    assert result.tool_called == "submit_leave_request"
    assert db.scalar(select(LeaveRequest)) is not None
