"""Leave agent — placeholder node for the supervisor graph.

The leave capability layer (``capabilities/leave.py``) already exists, but
wiring it into the graph (balances, requests, approvals with identity
resolution) is a later slice. Until then the node answers honestly instead of
pretending to act.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.agents.supervisor.state import SupervisorState

_LEAVE_STUB = (
    "Leave isn't available in chat yet. Please use the **Leave** section in "
    "the portal to request leave or check your balance."
)


def make_leave_node():
    """Build the leave node: honest placeholder until the leave agent lands."""

    async def leave_node(state: SupervisorState, writer: StreamWriter) -> dict:
        writer({"type": "message", "text": _LEAVE_STUB})
        return {
            "messages": [AIMessage(content=_LEAVE_STUB)],
            "knowledge_result": None,
            "answer": _LEAVE_STUB,
            "citations": [],
            "confidence": 0.0,
            "agent": "leave",
        }

    return leave_node
