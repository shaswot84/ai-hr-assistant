"""Data access for durable agent workflow state (conversation_workflow_state)."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversation import ConversationWorkflowState
from app.shared.clock import get_clock

STATUS_ACTIVE = "ACTIVE"
STATUS_COMPLETED = "COMPLETED"

WORKFLOW_TYPE_LEAVE = "LEAVE"


class WorkflowStateRepo:
    """Data access for conversation_workflow_state rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def get_active(
        self, conversation_id: uuid.UUID, actor_user_id: uuid.UUID
    ) -> ConversationWorkflowState | None:
        """The conversation's resumable workflow row, or None if there is none.

        Only ACTIVE rows are ever restored — a COMPLETED workflow is terminal
        and a fresh session starts from scratch.
        """
        stmt = select(ConversationWorkflowState).where(
            ConversationWorkflowState.conversation_id == conversation_id,
            ConversationWorkflowState.actor_user_id == actor_user_id,
            ConversationWorkflowState.status == STATUS_ACTIVE,
        )
        return await self._db.scalar(stmt)

    async def create(
        self,
        *,
        conversation_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        workflow_type: str = WORKFLOW_TYPE_LEAVE,
    ) -> ConversationWorkflowState:
        """Persist a new ACTIVE workflow row and flush to obtain its id."""
        now = get_clock().utc_now()
        row = ConversationWorkflowState(
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            workflow_type=workflow_type,
            status=STATUS_ACTIVE,
            draft_request=None,
            pending_confirmation=None,
            expires_at=None,
            created_at=now,
            updated_at=now,
        )
        self._db.add(row)
        await self._db.flush()
        return row

    async def update(
        self,
        row: ConversationWorkflowState,
        *,
        draft_request: dict | None,
        pending_confirmation: dict | None,
        expires_at,
    ) -> None:
        """Overwrite the row's durable workflow payload (draft, staged action, expiry)."""
        row.draft_request = draft_request
        row.pending_confirmation = pending_confirmation
        row.expires_at = expires_at
        row.updated_at = get_clock().utc_now()

    async def complete(self, row: ConversationWorkflowState) -> None:
        """Mark the workflow terminal so it is never restored again."""
        row.status = STATUS_COMPLETED
        row.updated_at = get_clock().utc_now()


