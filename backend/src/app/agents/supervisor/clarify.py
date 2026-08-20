"""Clarify node: handles ambiguous or off-topic messages.

For v1 this is deliberately deterministic — a fixed, helpful question that
lists the areas the assistant can help with. An LLM-generated clarifying
question adds polish but no routing value; the route node already used the
LLM to decide the message was ambiguous.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.agents.supervisor.state import SupervisorState

_CLARIFY_MESSAGE = """Could you clarify what you'd like help with? I can assist with:

- **Company policy & knowledge** — HR policy, procedures, guidelines, benefits
- **Leave** — balances, requests, approvals
- **Recruitment** — vacancies, applications, hiring

For example: "What is the annual leave policy?" or "How do I apply for the Data Analyst vacancy?" """


def make_clarify_node():
    """Build the clarify node: asks which area the user meant, using hint when available."""

    async def clarify_node(state: SupervisorState, writer: StreamWriter) -> dict:
        hint = state.get("clarification_hint")
        if hint:
            message = (
                f"{hint}\n\n"
                "Could you please clarify what you'd like help with? I can assist with:\n\n"
                "- **Company policy & knowledge** — HR policy, procedures, guidelines, benefits\n"
                "- **Leave** — balances, requests, approvals\n"
                "- **Recruitment** — vacancies, applications, hiring"
            )
        else:
            message = _CLARIFY_MESSAGE

        writer({"type": "message", "text": message})
        return {
            "messages": [AIMessage(content=message)],
            "knowledge_result": None,
            "answer": message,
            "citations": [],
            "confidence": 0.0,
            "agent": "clarify",
            "can_handle": True,
            "clarification_hint": None,
        }

    return clarify_node
