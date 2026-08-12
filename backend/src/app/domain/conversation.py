from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Conversation(Base):
    """A durable multi-turn chat session between a user and the assistant.

    The single source of truth for chat history: every turn is appended to
    ``conversation_message`` rows before the supervisor graph runs, so a
    crash, restart, or scale-out never loses context. The LangGraph state is
    hydrated from this table on each turn rather than from LangGraph's own
    checkpointer (which is psycopg-based while this app's async engine is
    asyncpg-based) — see the conversation repository.
    """

    __tablename__ = "conversation"

    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Nullable: candidates and anonymous visitors may also chat (e.g. from the
    # public careers page) even though the primary audience is employees.
    employee_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("employee.employee_id"), nullable=True
    )
    # Set from the first user message so the history list is readable without
    # loading every message.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_conversation_employee_updated", Conversation.employee_id, Conversation.updated_at)


class ConversationMessage(Base):
    """One turn in a conversation (user utterance or assistant reply).

    ``citations`` and ``meta`` are JSON because their shape evolves with the
    agent implementation (grounded context, confidence, chunk ids, which
    agent handled the turn, ...) — a JSON document is cheaper to evolve than
    a fixed set of columns. ``sequence_no`` is the deterministic order key:
    ``created_at`` alone can tie in fast sequences.
    """

    __tablename__ = "conversation_message"

    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversation.conversation_id", ondelete="CASCADE")
    )
    # Monotonic per conversation.
    sequence_no: Mapped[int] = mapped_column(Integer)
    # user | assistant | system
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    # Source documents cited in an assistant reply: [{document_title, ...}]
    citations: Mapped[list[dict] | None] = mapped_column(JSON, nullable=True)
    # Agent-specific payload (confidence, retrieved chunk ids, ...) —
    # deliberately opaque here.
    meta: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "ix_conversation_message_conversation_seq",
    ConversationMessage.conversation_id,
    ConversationMessage.sequence_no,
)
