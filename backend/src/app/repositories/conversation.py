"""Data access for durable chat conversations (async session).

Async because the chat pipeline this feeds — SSE streaming, LLM calls, the
KnowledgeService — is fully async. The supervisor graph hydrates its state
from here on each turn: this repository is the single place that touches
conversation rows.
"""

from __future__ import annotations

import uuid

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.conversation import Conversation, ConversationMessage, ConversationWorkflowState
from app.shared.clock import get_clock


class ConversationRepo:
    """Data access for conversation and conversation_message rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, *, user_id: uuid.UUID, title: str | None = None) -> Conversation:
        """Persist a new conversation for an authenticated user and flush."""
        now = get_clock().utc_now()
        conversation = Conversation(
            user_id=user_id, title=title, created_at=now, updated_at=now
        )
        self._db.add(conversation)
        await self._db.flush()
        return conversation

    async def get(self, conversation_id: uuid.UUID) -> Conversation | None:
        """Fetch a conversation by id, or None if it does not exist."""
        return await self._db.get(Conversation, conversation_id)

    async def delete(self, conversation_id: uuid.UUID) -> bool:
        """Delete a conversation by id, removing associated messages and workflow states.

        Returns True if deleted, False if not found.
        """
        conversation = await self.get(conversation_id)
        if conversation is None:
            return False
        await self._db.execute(
            delete(ConversationMessage).where(ConversationMessage.conversation_id == conversation_id)
        )
        await self._db.execute(
            delete(ConversationWorkflowState).where(
                ConversationWorkflowState.conversation_id == conversation_id
            )
        )
        await self._db.delete(conversation)
        await self._db.flush()
        return True

    async def list_for_user(self, user_id: uuid.UUID, *, limit: int = 50) -> list[Conversation]:
        """List a user's conversations, most recently active first.

        ``conversation_id`` breaks ties on equal timestamps so pagination
        order is deterministic.
        """
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.conversation_id.desc())
            .limit(limit)
        )
        return list((await self._db.scalars(stmt)).all())

    async def set_title(self, conversation_id: uuid.UUID, title: str) -> None:
        """Set (or overwrite) the conversation's display title."""
        await self._db.execute(
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(title=title)
        )

    async def touch(self, conversation_id: uuid.UUID) -> None:
        """Bump ``updated_at`` so the conversation rises in the history list."""
        await self._db.execute(
            update(Conversation)
            .where(Conversation.conversation_id == conversation_id)
            .values(updated_at=get_clock().utc_now())
        )

    async def append_message(
        self,
        *,
        conversation_id: uuid.UUID,
        role: str,
        content: str,
        citations: list[dict] | None = None,
        meta: dict | None = None,
    ) -> ConversationMessage:
        """Append one turn with the next sequence number and flush."""
        message = ConversationMessage(
            conversation_id=conversation_id,
            sequence_no=await self._next_sequence(conversation_id),
            role=role,
            content=content,
            citations=citations,
            meta=meta,
            created_at=get_clock().utc_now(),
        )
        self._db.add(message)
        await self._db.flush()
        return message

    async def list_messages(self, conversation_id: uuid.UUID) -> list[ConversationMessage]:
        """Every message in a conversation, oldest first."""
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no.asc())
        )
        return list((await self._db.scalars(stmt)).all())

    async def recent_messages(
        self, conversation_id: uuid.UUID, n: int
    ) -> list[ConversationMessage]:
        """The last ``n`` messages, oldest of the window first.

        This is the window the supervisor's routing prompt and the knowledge
        agent's query-rewrite prompt see — bounded so prompt size and latency
        stay predictable.
        """
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no.desc())
            .limit(n)
        )
        rows = list((await self._db.scalars(stmt)).all())
        rows.reverse()
        return rows

    async def recent_messages_within_tokens(
        self, conversation_id: uuid.UUID, token_budget: int
    ) -> list[ConversationMessage]:
        """The newest messages whose combined estimated size fits the budget.

        Bounded by token count, not message count, using a deterministic
        4-characters-per-token estimate (never a model call): a conversation
        of short messages gets more turns of context, one of long messages
        gets fewer, and the prompt stays within the budget regardless.
        """
        stmt = (
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no.desc())
            .limit(5000)
        )
        rows = list((await self._db.scalars(stmt)).all())

        window: list[ConversationMessage] = []
        used = 0
        for row in rows:  # newest first
            cost = max(1, len(row.content) // 4)
            if window and used + cost > token_budget:
                break
            window.append(row)
            used += cost
        window.reverse()
        return window

    async def _next_sequence(self, conversation_id: uuid.UUID) -> int:
        """The next sequence number for a conversation (max existing + 1)."""
        stmt = (
            select(ConversationMessage.sequence_no)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.sequence_no.desc())
            .limit(1)
        )
        last = await self._db.scalar(stmt)
        return (last or 0) + 1
