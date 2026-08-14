"""Recruitment agent — placeholder node for the supervisor graph.

Like the leave agent, the recruitment capability layer
(``capabilities/recruitment.py``) already exists but is not yet wired into
the graph. Until then the node answers honestly instead of pretending to act.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.agents.supervisor.state import SupervisorState

_RECRUITMENT_STUB = (
    "Recruitment isn't available in chat yet. Please use the **Careers** "
    "section of the portal to browse vacancies and manage applications."
)


def make_recruitment_node():
    """Build the recruitment node: honest placeholder until the agent lands."""

    async def recruitment_node(state: SupervisorState, writer: StreamWriter) -> dict:
        writer({"type": "message", "text": _RECRUITMENT_STUB})
        return {
            "messages": [AIMessage(content=_RECRUITMENT_STUB)],
            "knowledge_result": None,
            "answer": _RECRUITMENT_STUB,
            "citations": [],
            "confidence": 0.0,
            "agent": "recruitment",
        }

    return recruitment_node
