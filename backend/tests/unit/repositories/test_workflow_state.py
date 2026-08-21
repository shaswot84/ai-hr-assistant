"""WorkflowStateRepo: durable conversation_workflow_state rows."""

from __future__ import annotations

import uuid

from app.repositories.workflow_state import (
    STATUS_ACTIVE,
    STATUS_COMPLETED,
    WorkflowStateRepo,
)


def _new_id() -> uuid.UUID:
    return uuid.uuid4()



async def test_create_and_get_active(db):
    repo = WorkflowStateRepo(db)
    conversation_id = _new_id()
    actor_user_id = _new_id()

    row = await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)
    await db.commit()

    assert row.status == STATUS_ACTIVE
    assert row.workflow_type == "LEAVE"
    assert row.draft_request is None
    assert row.pending_confirmation is None
    assert row.expires_at is None

    fetched = await repo.get_active(conversation_id, actor_user_id)
    assert fetched is not None
    assert fetched.workflow_state_id == row.workflow_state_id


async def test_get_active_scoped_by_conversation_and_actor(db):
    repo = WorkflowStateRepo(db)
    conversation_id = _new_id()
    actor_user_id = _new_id()
    await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)
    await db.commit()

    assert await repo.get_active(_new_id(), actor_user_id) is None
    assert await repo.get_active(conversation_id, _new_id()) is None


async def test_update_overwrites_payload(db):
    repo = WorkflowStateRepo(db)
    conversation_id = _new_id()
    actor_user_id = _new_id()
    row = await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)

    await repo.update(
        row,
        draft_request={"leave_type_name": "Annual Leave", "start_date": "2026-09-01"},
        pending_confirmation={
            "tool": "submit_leave_request",
            "args": {"leave_type_name": "Annual Leave"},
        },
        expires_at=None,
    )
    await db.commit()

    fetched = await repo.get_active(conversation_id, actor_user_id)
    assert fetched.draft_request == {"leave_type_name": "Annual Leave", "start_date": "2026-09-01"}
    assert fetched.pending_confirmation["tool"] == "submit_leave_request"


async def test_complete_marks_terminal_and_hides_from_get_active(db):
    repo = WorkflowStateRepo(db)
    conversation_id = _new_id()
    actor_user_id = _new_id()
    row = await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)

    await repo.complete(row)
    await db.commit()

    assert row.status == STATUS_COMPLETED
    assert await repo.get_active(conversation_id, actor_user_id) is None


async def test_create_then_complete_then_new_active_row_for_same_conversation(db):
    """The partial unique index allows exactly one ACTIVE row per
    conversation+actor — a completed workflow frees the slot for a new one."""
    repo = WorkflowStateRepo(db)
    conversation_id = _new_id()
    actor_user_id = _new_id()

    first = await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)
    await repo.complete(first)
    await db.commit()

    second = await repo.create(conversation_id=conversation_id, actor_user_id=actor_user_id)
    await db.commit()

    fetched = await repo.get_active(conversation_id, actor_user_id)
    assert fetched is not None
    assert fetched.workflow_state_id == second.workflow_state_id