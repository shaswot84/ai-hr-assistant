"""Leave Agent LangGraph node: the adapter between the supervisor graph and
the dispatch loop in ``agent.py``.

The supervisor graph routes the turn here (``SupervisorState``), and this
node adapts it into ``handle_turn``'s request/response shape, then maps the
result back into state updates the chat layer persists (answer, agent,
confidence, safety).

Wiring notes:

- The node is built per request with the request's ``actor``, a shared
  ``SessionStore`` (process-wide, keyed by conversation id — see
  ``state.py``), and a ``ChatProvider``.
- ``SessionStore`` is a CACHE only. On a miss, this node restores the leave
  workflow state from the durable ``conversation_workflow_state`` row
  (``WorkflowStateRepo``); after the turn it writes any workflow changes
  (draft / staged confirmation / expiry) back, or marks the workflow
  COMPLETED once it is terminal. The durable transcript in
  ``conversation_message`` is untouched by both paths — the row never
  duplicates history.
- ``handle_turn`` is the single place that owns leave business logic; this
  module only translates between the two contracts.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter
from openinference.semconv.trace import SpanAttributes
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import (
    LeaveAgentState,
    SessionStore,
    apply_workflow_snapshot,
    workflow_snapshot,
)
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.db.session import async_session_factory
from app.model_gateway.provider import ChatProvider
from app.observability import trace_agent_turn
from app.repositories.workflow_state import WorkflowStateRepo
from app.services.identity import IdentityError, IdentityService
from app.shared.clock import get_clock

if TYPE_CHECKING:
    from app.agents.supervisor.state import SupervisorState


def make_leave_node(
    *,
    actor: UserContext,
    store: SessionStore,
    chat_provider: ChatProvider,
    leave_service: LeaveService | None = None,
) -> Callable[[SupervisorState, StreamWriter], Awaitable[dict]]:
    """Build the leave node for the supervisor graph."""

    async def leave_node(state: SupervisorState, writer: StreamWriter) -> dict:
        conversation_id = state.get("conversation_id", "default")

        # Cache-first: the store is never the source of truth. Only when the
        # cache misses does the durable row get consulted (or a fresh state
        # created), and every workflow change is written back after the turn.
        leave_state = store.get(conversation_id, actor)
        if leave_state is None:
            leave_state = await _restore_or_create(actor, store, conversation_id)

        # Bind the store-backed execution claim for this turn: a confirmed
        # write is claimed atomically per session (in-memory set, or a Redis
        # SET NX EX lock when REDIS_URL is configured) so two workers can
        # never both execute the same confirmation.
        leave_state.bind_claim(
            lambda: store.begin_execution(conversation_id),
            lambda: store.end_execution(conversation_id),
        )

        result = await _run_turn(actor, chat_provider, leave_state, state, writer, leave_service)

        await _persist_workflow(actor, conversation_id, leave_state)
        # The working slice (history included) goes back to the store: for
        # Redis this is what lets a turn landing on another worker see the
        # same conversation memory; for the in-memory store it is a no-op
        # re-put of the same shared object.
        store.put(leave_state)
        return result

    return leave_node


async def _restore_or_create(actor: UserContext, store: SessionStore, conversation_id: str) -> LeaveAgentState:
    """Rebuild the session's leave state from the durable workflow row."""
    async with async_session_factory() as db:
        user_id = await _actor_user_id(db, actor)
        if user_id is not None:
            row = await WorkflowStateRepo(db).get_active(uuid.UUID(conversation_id), user_id)
            if row is not None and row.workflow_type == "LEAVE":
                now = get_clock().now()
                restored = LeaveAgentState(
                    session_id=conversation_id,
                    actor_subject=actor.subject,
                    created_at=now,
                    updated_at=now,
                )
                apply_workflow_snapshot(
                    restored,
                    {
                        "draft": row.draft_request,
                        "pending": row.pending_confirmation,
                        "expires_at": (
                            row.expires_at.isoformat() if row.expires_at is not None else None
                        ),
                    },
                    clock=get_clock(),
                )
                store.put(restored)
                return restored
    return store.get_or_create(conversation_id, actor)


async def _persist_workflow(actor: UserContext, conversation_id: str, leave_state: LeaveAgentState) -> None:
    """Write the durable slice of leave state back to the workflow row."""
    snapshot = workflow_snapshot(leave_state)
    async with async_session_factory() as db:
        user_id = await _actor_user_id(db, actor)
        if user_id is None:
            return
        repo = WorkflowStateRepo(db)
        row = await repo.get_active(uuid.UUID(conversation_id), user_id)
        if not _workflow_changed(row, snapshot):
            return

        if snapshot["draft"] is None and snapshot["pending"] is None:
            if row is not None:
                await repo.complete(row)
                await db.commit()
            return

        if row is None:
            row = await repo.create(conversation_id=uuid.UUID(conversation_id), actor_user_id=user_id)
        await repo.update(
            row,
            draft_request=snapshot["draft"],
            pending_confirmation=snapshot["pending"],
            expires_at=_iso_to_datetime(snapshot["expires_at"]),
        )
        await db.commit()


def _workflow_changed(row, snapshot: dict) -> bool:
    """Whether the stored row differs from the state's current durable slice."""
    if row is None:
        return snapshot["draft"] is not None or snapshot["pending"] is not None
    if row.draft_request != snapshot["draft"] or row.pending_confirmation != snapshot["pending"]:
        return True
    stored = row.expires_at
    fresh = _iso_to_datetime(snapshot["expires_at"])
    if stored is None or fresh is None:
        return stored is not fresh
    return stored.replace(tzinfo=UTC) != fresh.replace(tzinfo=UTC)


def _iso_to_datetime(value: str | None):
    """ISO string -> datetime for the row's expires_at column (None stays None)."""
    if value is None:
        return None
    return datetime.fromisoformat(value)


async def _actor_user_id(db: AsyncSession, actor: UserContext) -> uuid.UUID | None:
    """The actor's application_user id, best-effort."""
    try:
        user = await IdentityService(db)._get_app_user(actor)
        return user.user_id
    except IdentityError:
        return None


async def _run_turn(
    actor: UserContext,
    chat_provider: ChatProvider,
    leave_state,
    state: SupervisorState,
    writer: StreamWriter,
    leave_service: LeaveService | None,
) -> dict:
    """Run one turn with a request-scoped service unless one was injected."""
    if leave_service is not None:
        return await _handle(actor, chat_provider, leave_state, state, writer, leave_service)

    async with async_session_factory() as db:
        return await _handle(actor, chat_provider, leave_state, state, writer, LeaveService(db))


async def _handle(
    actor: UserContext,
    chat_provider: ChatProvider,
    leave_state,
    state: SupervisorState,
    writer: StreamWriter,
    service: LeaveService,
) -> dict:
    async with trace_agent_turn(
        "leave",
        query=state["current_query"],
        conversation_id=state.get("conversation_id"),
        user_id=actor.subject if actor else None,
    ) as span:
        result = await handle_turn(
            actor=actor,
            state=leave_state,
            service=service,
            chat_provider=chat_provider,
            user_message=state["current_query"],
        )
        writer({"type": "message", "text": result.reply})
        if result.ui_widget:
            writer({"type": "ui_widget", "widget": result.ui_widget})
        span.set_attribute(SpanAttributes.OUTPUT_VALUE, result.reply)
        return {
            "messages": [AIMessage(content=result.reply)],
            "knowledge_result": None,
            "answer": result.reply,
            "citations": [],
            "confidence": 0.0,
            "agent": "leave",
            "safety": "PASS",
            "ui_widget": result.ui_widget,
        }