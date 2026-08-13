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
- ``handle_turn`` is the single place that owns leave business logic; this
  module only translates between the two contracts.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import SessionStore
from app.agents.supervisor.state import SupervisorState
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.db.sync_session import SessionLocal
from app.model_gateway.provider import ChatProvider


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
        leave_state = store.get_or_create(conversation_id, actor)
        return await _run_turn(actor, chat_provider, leave_state, state, writer, leave_service)

    return leave_node


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
    return {
        "messages": [AIMessage(content=result.reply)],
        "knowledge_result": None,
        "answer": result.reply,
        "citations": [],
        "confidence": 0.0,
        "agent": "leave",
        "safety": "PASS",
    }