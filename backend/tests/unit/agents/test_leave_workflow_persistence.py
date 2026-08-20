"""Leave workflow durability: SessionStore cache + conversation_workflow_state.

Exercises make_leave_node end to end. The store is a cache only: on a miss
the node restores the draft / staged confirmation from the durable row, and
after every leave turn it persists workflow changes (or marks the workflow
COMPLETED once it is terminal) — while never touching the transcript.
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select

from app.agents.leave_agent.node import make_leave_node
from app.agents.leave_agent.state import SessionStore
from app.capabilities.leave import LeaveService
from app.domain.conversation import Conversation, ConversationMessage, ConversationWorkflowState
from app.domain.leave import LeaveRequest
from app.repositories.workflow_state import STATUS_ACTIVE, STATUS_COMPLETED, WorkflowStateRepo
from app.services.identity import IdentityService
from app.shared.clock import get_clock


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


def _create_leave_type(svc, actor, *, name="Annual Leave", default_days=20):
    return svc.create_leave_type(
        actor,
        leave_name=name,
        description="Planned time off.",
        default_days=Decimal(default_days),
        requires_approval=True,
        is_paid=True,
        max_consecutive_days=None,
    )


def _seed_conversation(db, user_id: uuid.UUID) -> uuid.UUID:
    now = get_clock().utc_now()
    conversation = Conversation(user_id=user_id, title="Leave chat", created_at=now, updated_at=now)
    db.add(conversation)
    db.flush()
    return conversation.conversation_id


def _user_id(db, actor) -> uuid.UUID:
    return IdentityService(db)._get_app_user(actor).user_id


def _workflow_row(db, conversation_id: uuid.UUID, actor):
    return WorkflowStateRepo(db).get_active(conversation_id, _user_id(db, actor))


def _request_count(db) -> int:
    return db.scalar(select(func.count(LeaveRequest.leave_request_id)))


async def _run_node(actor, store, provider, service, conversation_id, message):
    node = make_leave_node(actor=actor, store=store, chat_provider=provider, leave_service=service)
    return await node(
        {"conversation_id": str(conversation_id), "current_query": message, "messages": []},
        lambda chunk: None,
    )


@pytest.mark.asyncio
async def test_new_conversation_persists_draft_row(
    db, manager_context, employee_context
):
    """A first leave turn with a resolvable start date creates the workflow
    row with the deterministically resolved draft (never the model's words)."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    store = SessionStore()

    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )

    row = _workflow_row(db, conversation_id, employee_context)
    assert row is not None
    assert row.status == STATUS_ACTIVE
    assert row.workflow_type == "LEAVE"
    assert row.draft_request["leave_type_name"] == "Annual Leave"
    assert row.draft_request["start_date"] == (get_clock().today() + timedelta(days=1)).isoformat()
    assert row.draft_request["end_date"] is None
    assert row.pending_confirmation is None


@pytest.mark.asyncio
async def test_draft_restored_after_cache_miss(db, manager_context, employee_context):
    """A cache miss restores the draft from the row; the follow-up end date is
    resolved against the RESTORED start — no model call, no re-derivation."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    first_store = SessionStore()
    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    assert _workflow_row(db, conversation_id, employee_context) is not None

    # Simulated restart: a brand-new process-wide store.
    second_store = SessionStore()
    provider = FakeChatProvider({})
    result = await _run_node(
        employee_context, second_store, provider, svc, conversation_id, "for 3 days",
    )

    assert provider.calls == 0
    assert "Annual Leave" in result["answer"]
    state = second_store.get(str(conversation_id), employee_context)
    assert state is not None
    assert state.pending_confirmation is not None
    start = get_clock().today() + timedelta(days=1)
    assert state.pending_confirmation.args == {
        "leave_type_name": "Annual Leave",
        "start_date": start.isoformat(),
        "end_date": (start + timedelta(days=2)).isoformat(),
        "is_half_day": False,
        "half_day_period": None,
        "reason": None,
    }


@pytest.mark.asyncio
async def test_pending_confirmation_persisted(db, manager_context, employee_context):
    """A staged write action is stored with its tool, canonical args, and TTL."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    store = SessionStore()

    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id, "for 3 days",
    )

    row = _workflow_row(db, conversation_id, employee_context)
    assert row is not None
    assert row.pending_confirmation is not None
    assert row.pending_confirmation["tool"] == "submit_leave_request"
    assert row.pending_confirmation["args"]["leave_type_name"] == "Annual Leave"
    assert row.expires_at is not None
    assert row.draft_request is None


@pytest.mark.asyncio
async def test_yes_after_restart_executes_persisted_confirmation(
    db, manager_context, employee_context
):
    """After a restart, a "yes" executes the PERSISTED staged action — the
    confirmation survives the SessionStore and is honored from the row."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    first_store = SessionStore()

    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id, "for 3 days",
    )
    row = _workflow_row(db, conversation_id, employee_context)
    staged_args = row.pending_confirmation["args"]

    second_store = SessionStore()
    provider = FakeChatProvider(
        {
            "reply": "Submitting.",
            "action": "call_tool",
            "tool": "submit_leave_request",
            "args": staged_args,
        }
    )
    result = await _run_node(
        employee_context, second_store, provider, svc, conversation_id, "yes",
    )

    assert provider.calls == 1
    assert "submitted" in result["answer"]
    assert _request_count(db) == 1
    db.expire_all()
    assert _workflow_row(db, conversation_id, employee_context) is None

    terminal = db.scalar(
        select(ConversationWorkflowState).where(
            ConversationWorkflowState.conversation_id == conversation_id
        )
    )
    assert terminal is not None
    assert terminal.status == STATUS_COMPLETED


@pytest.mark.asyncio
async def test_cache_expiry_restores_and_executes_persisted_confirmation(
    db, manager_context, employee_context
):
    """SessionStore TTL expiry (not a restart) is a miss like any other: the
    staged confirmation is restored from the row and "yes" executes it."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    store = SessionStore(ttl=timedelta(seconds=0))  # every get() misses

    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id, "for 3 days",
    )
    row = _workflow_row(db, conversation_id, employee_context)
    staged_args = row.pending_confirmation["args"]

    provider = FakeChatProvider(
        {
            "reply": "Submitting.",
            "action": "call_tool",
            "tool": "submit_leave_request",
            "args": staged_args,
        }
    )
    result = await _run_node(
        employee_context, store, provider, svc, conversation_id, "yes",
    )

    assert provider.calls == 1
    assert "submitted" in result["answer"]
    assert _request_count(db) == 1


@pytest.mark.asyncio
async def test_expired_confirmation_rejected_deterministically(
    db, manager_context, employee_context
):
    """A persisted confirmation past its TTL is dropped at restore and can
    never execute — the persisted expires_at decides, not the model."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    first_store = SessionStore()

    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id, "for 3 days",
    )

    # Age the persisted confirmation past its TTL (reassign the JSON so
    # the change is flushed).
    row = _workflow_row(db, conversation_id, employee_context)
    old = (get_clock().now() - timedelta(minutes=6)).isoformat()
    pending = dict(row.pending_confirmation)
    pending["expires_at"] = old
    row.pending_confirmation = pending
    row.expires_at = get_clock().now() - timedelta(minutes=6)
    db.commit()

    second_store = SessionStore()
    provider = FakeChatProvider(
        {
            "reply": "Confirming.",
            "action": "call_tool",
            "tool": "submit_leave_request",
            "args": row.pending_confirmation["args"],
        }
    )
    result = await _run_node(
        employee_context, second_store, provider, svc, conversation_id, "yes",
    )

    assert _request_count(db) == 0
    assert provider.calls == 1  # the model spoke, but the gate rejected
    assert "staged" in result["answer"]

    # The abandoned workflow is marked terminal (never resurrected).
    db.expire_all()
    terminal = db.scalar(
        select(ConversationWorkflowState).where(
            ConversationWorkflowState.conversation_id == conversation_id
        )
    )
    assert terminal.status == STATUS_COMPLETED


@pytest.mark.asyncio
async def test_completed_workflow_not_restored(db, manager_context, employee_context):
    """After the workflow completes, a fresh session starts from scratch."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    first_store = SessionStore()

    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    await _run_node(
        employee_context, first_store, FakeChatProvider({}), svc, conversation_id, "for 3 days",
    )
    row = _workflow_row(db, conversation_id, employee_context)
    await _run_node(
        employee_context, first_store,
        FakeChatProvider(
            {
                "reply": "Submitting.",
                "action": "call_tool",
                "tool": "submit_leave_request",
                "args": row.pending_confirmation["args"],
            }
        ),
        svc, conversation_id, "yes",
    )
    assert _request_count(db) == 1

    fresh_store = SessionStore()
    provider = FakeChatProvider(
        {"reply": "No draft or staged action here.", "action": "reply", "tool": None, "args": {}}
    )
    result = await _run_node(
        employee_context, fresh_store, provider, svc, conversation_id, "any follow-up",
    )

    assert provider.calls == 1
    assert result["answer"] == "No draft or staged action here."
    state = fresh_store.get(str(conversation_id), employee_context)
    assert state.draft is None
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_noop_turn_writes_nothing(db, manager_context, employee_context):
    """Turns that change no workflow fact never touch the row: no row is
    created for a plain reply, and an existing row is not rewritten."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    db.commit()
    store = SessionStore()
    provider = FakeChatProvider(
        {"reply": "Sure, happy to help.", "action": "reply", "tool": None, "args": {}}
    )

    await _run_node(employee_context, store, provider, svc, conversation_id, "hello")
    assert _workflow_row(db, conversation_id, employee_context) is None

    await _run_node(
        employee_context, store, provider, svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )
    row = _workflow_row(db, conversation_id, employee_context)
    assert row is not None
    created_at = row.created_at
    draft = row.draft_request

    await _run_node(employee_context, store, provider, svc, conversation_id, "thanks")
    row = _workflow_row(db, conversation_id, employee_context)
    assert row.draft_request == draft
    assert row.created_at == created_at


@pytest.mark.asyncio
async def test_workflow_persistence_leaves_transcript_untouched(
    db, manager_context, employee_context
):
    """The workflow row stores only draft/pending facts — the transcript's
    messages are never duplicated, moved, or modified."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    conversation_id = _seed_conversation(db, _user_id(db, employee_context))
    now = get_clock().utc_now()
    db.add(
        ConversationMessage(
            conversation_id=conversation_id, sequence_no=1, role="user",
            content="original user message", created_at=now,
        )
    )
    db.add(
        ConversationMessage(
            conversation_id=conversation_id, sequence_no=2, role="assistant",
            content="original assistant message", created_at=now,
        )
    )
    db.commit()
    store = SessionStore()

    await _run_node(
        employee_context, store, FakeChatProvider({}), svc, conversation_id,
        "i want to apply for annual leave tomorrow",
    )

    messages = db.scalars(
        select(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
    ).all()
    assert [(m.role, m.content) for m in messages] == [
        ("user", "original user message"),
        ("assistant", "original assistant message"),
    ]

    row = _workflow_row(db, conversation_id, employee_context)
    assert set(row.draft_request) == {
        "leave_type_name",
        "start_date",
        "end_date",
        "is_half_day",
        "half_day_period",
        "reason",
    }
    assert row.pending_confirmation is None