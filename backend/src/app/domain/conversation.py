from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
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
    # The authenticated owner. Keyed on application_user.user_id (not
    # employee_id): every authenticated role — HR_ADMIN, EMPLOYEE, CANDIDATE —
    # has an application_user row, but candidates have no employee row.
    # Candidates chat through the guarded /candidate/chatbot portal, so angit
    # employee_id key would silently bar them from durable history; a user_id
    # key also stays stable across the candidate -> employee hire transition.
    # The employee (if any) is derived at runtime via IdentityService, never
    # stored here.
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("application_user.user_id"), nullable=False
    )
    # Set from the first user message so the history list is readable without
    # loading every message.
    title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index("ix_conversation_user_updated", Conversation.user_id, Conversation.updated_at)


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


class ConversationWorkflowState(Base):
    """Durable per-conversation workflow state for an agent (currently LEAVE).

    Sits between the two existing layers: the durable transcript
    (``conversation``/``conversation_message``) and the in-memory session
    store. It holds ONLY the workflow facts the session store is allowed to
    lose — a partially collected request draft and a staged write action
    awaiting confirmation (with its expiry). The transcript owns history;
    this row never duplicates a single message.

    ``status`` is ACTIVE while the workflow has anything worth resuming,
    COMPLETED once the staged action executed or the workflow ended — a
    completed row is never restored into a fresh session. The partial unique
    index enforces at most one ACTIVE workflow per conversation+actor.
    """

    __tablename__ = "conversation_workflow_state"

    workflow_state_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("conversation.conversation_id", ondelete="CASCADE"), nullable=False
    )
    actor_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("application_user.user_id"), nullable=False
    )
    workflow_type: Mapped[str] = mapped_column(String(50), default="LEAVE")
    # ACTIVE (resumable) | COMPLETED (terminal — never restored).
    status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    # JSON-safe shapes — see leave_agent/state.py (draft_to_json /
    # pending_to_json): dates and datetimes are ISO strings, never ORM objects.
    draft_request: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    pending_confirmation: Mapped[dict | None] = mapped_column(
        JSON().with_variant(JSONB(), "postgresql"), nullable=True
    )
    # When the staged action (if any) expires — persisted so a process
    # restart can never extend a confirmation's life.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


Index(
    "uq_conversation_workflow_active",
    ConversationWorkflowState.conversation_id,
    ConversationWorkflowState.actor_user_id,
    unique=True,
    sqlite_where=text("status = 'ACTIVE'"),
    postgresql_where=text("status = 'ACTIVE'"),
)
Index(
    "ix_conversation_workflow_actor_status",
    ConversationWorkflowState.actor_user_id,
    ConversationWorkflowState.status,
)
