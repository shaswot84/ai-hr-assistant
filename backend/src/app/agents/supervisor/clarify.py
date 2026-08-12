"""Clarify node: handles ambiguous or off-topic messages.

For v1 this is deliberately deterministic — a fixed, helpful question that
lists the areas the assistant can help with. An LLM-generated clarifying
question adds polish but no routing value; the route node already used the
LLM to decide the message was ambiguous.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from app.agents.supervisor.state import SupervisorState

_CLARIFY_MESSAGE = """Could you clarify what you'd like help with? I can assist with:

- **Company policy & knowledge** — HR policy, procedures, guidelines, benefits
- **Leave** — balances, requests, approvals
- **Recruitment** — vacancies, applications, hiring

For example: "What is the annual leave policy?" or "How do I apply for the Data Analyst vacancy?" """


def make_clarify_node():
    """Build the clarify node: asks which area the user meant."""

    async def clarify_node(state: SupervisorState) -> dict:
        return {
            "messages": [AIMessage(content=_CLARIFY_MESSAGE)],
            "knowledge_result": None,
            "answer": _CLARIFY_MESSAGE,
            "citations": [],
            "confidence": 0.0,
            "agent": "clarify",
        }

    return clarify_node
