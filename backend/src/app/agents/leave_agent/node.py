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

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import (
    LeaveAgentState,
    SessionStore,
    apply_workflow_snapshot,
    workflow_snapshot,
)
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.db.sync_session import SessionLocal
from app.model_gateway.provider import ChatProvider
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
    """Build the leave node for the supervisor graph.

    ``leave_service`` may be injected for tests; otherwise a request-scoped
    service is built on the sync session (the same pattern the CLI uses).
    """
    async def leave_node(state: SupervisorState, writer: StreamWriter) -> dict:
        conversation_id = state.get("conversation_id", "default")

        # Cache-first: the store is never the source of truth. Only when the
        # cache misses does the durable row get consulted (or a fresh state
        # created), and every workflow change is written back after the turn.
        leave_state = store.get(conversation_id, actor)
        if leave_state is None:
            leave_state = _restore_or_create(actor, store, conversation_id)

        # Bind the store-backed execution claim for this turn: a confirmed
        # write is claimed atomically per session (in-memory set, or a Redis
        # SET NX EX lock when REDIS_URL is configured) so two workers can
        # never both execute the same confirmation.
        leave_state.bind_claim(
            lambda: store.begin_execution(conversation_id),
            lambda: store.end_execution(conversation_id),
        )

        result = await _run_turn(actor, chat_provider, leave_state, state, writer, leave_service)

        _persist_workflow(actor, conversation_id, leave_state)
        # The working slice (history included) goes back to the store: for
        # Redis this is what lets a turn landing on another worker see the
        # same conversation memory; for the in-memory store it is a no-op
        # re-put of the same shared object.
        store.put(leave_state)
        return result

    return leave_node


def _restore_or_create(actor: UserContext, store: SessionStore, conversation_id: str) -> LeaveAgentState:
    """Rebuild the session's leave state from the durable workflow row.

    When the conversation has an ACTIVE workflow row the draft and staged
    confirmation are restored into the cached state (an expired staged
    action is dropped deterministically at restore time — the persisted
    ``expires_at`` decides, never the model). Otherwise a fresh state is
    created exactly as before this layer existed.
    """
    with SessionLocal() as db:
        user_id = _actor_user_id(db, actor)
        if user_id is not None:
            row = WorkflowStateRepo(db).get_active(uuid.UUID(conversation_id), user_id)
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


def _persist_workflow(actor: UserContext, conversation_id: str, leave_state: LeaveAgentState) -> None:
    """Write the durable slice of leave state back to the workflow row.

    The stored row is compared with the state's current snapshot; when
    nothing about the draft or staged action changed, no write happens. A
    snapshot with nothing to resume marks an existing ACTIVE row COMPLETED —
    a finished workflow is never restored into a future session.
    """
    snapshot = workflow_snapshot(leave_state)
    with SessionLocal() as db:
        user_id = _actor_user_id(db, actor)
        if user_id is None:
            return
        repo = WorkflowStateRepo(db)
        row = repo.get_active(uuid.UUID(conversation_id), user_id)
        if not _workflow_changed(row, snapshot):
            return

        if snapshot["draft"] is None and snapshot["pending"] is None:
            if row is not None:
                repo.complete(row)
                db.commit()
            return

        if row is None:
            row = repo.create(conversation_id=uuid.UUID(conversation_id), actor_user_id=user_id)
        repo.update(
            row,
            draft_request=snapshot["draft"],
            pending_confirmation=snapshot["pending"],
            expires_at=_iso_to_datetime(snapshot["expires_at"]),
        )
        db.commit()


def _workflow_changed(row, snapshot: dict) -> bool:
    """Whether the stored row differs from the state's current durable slice.

    ``expires_at`` is compared by instant: SQLite's DATETIME column drops
    tzinfo, so the stored value may be naive while the snapshot is
    tz-aware — both are UTC instants, and only the instant matters for the
    no-op check.
    """
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


def _actor_user_id(db, actor: UserContext) -> uuid.UUID | None:
    """The actor's application_user id, best-effort: an actor without an
    application_user row (never the case for authenticated chat, possible in
    tests) simply gets no durable workflow — state stays in-memory only."""
    try:
        return IdentityService(db)._get_app_user(actor).user_id
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

    with SessionLocal() as db:
        return await _handle(actor, chat_provider, leave_state, state, writer, LeaveService(db))


async def _handle(
    actor: UserContext,
    chat_provider: ChatProvider,
    leave_state,
    state: SupervisorState,
    writer: StreamWriter,
    service: LeaveService,
) -> dict:
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