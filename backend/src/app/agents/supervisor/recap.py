"""Recap node: summarize what was discussed in THIS conversation.

Answers "what is this chat about?" / "what did we discuss?" — a recap
cannot be answered by any single sub-agent: the thread may mix knowledge,
leave, and recruitment turns, and only the leave path carries state beyond
the transcript (draft / staged confirmation). The node summarizes the
transcript only — it never calls tools or retrieval, so it can neither
invent facts nor leak anything that wasn't said in this thread.

Routing is deterministic (route_history_question): leave-scoped history
questions ("what leave did i apply above") go to the leave agent, whose
own deterministic interception answers them; generic thread questions go
here. The LLM is never asked to choose the recap route.
"""

from __future__ import annotations

import logging

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from openinference.semconv.trace import SpanAttributes

from app.agents.context import history_text, is_history_question
from app.agents.supervisor.state import SupervisorState
from app.model_gateway.interfaces import LLM
from app.observability import trace_agent_turn

logger = logging.getLogger(__name__)

# Words that make a history question LEAVE-scoped: the leave agent owns it
# (it can also surface its hidden workflow state). Anything else goes to the
# recap node, which sees the whole thread.
_LEAVE_HISTORY_WORDS = (
    "leave",
    "applied",
    "apply",
    "request",
    "requests",
    "submitted",
    "cancelled",
    "cancel",
    "balance",
)

_RECAP_SYSTEM = (
    "You summarize a chat conversation. The user asked what was discussed in "
    "this chat. Summarize the conversation below factually in 3-6 short bullet "
    "points covering every topic discussed. Use ONLY the conversation "
    "transcript — never add outside facts, never mention tools, retrieval, or "
    "a knowledge base. If the transcript is empty, state that nothing was "
    "discussed yet."
)

_FALLBACK_HEADER = "Here's what we discussed in this chat:"


def route_history_question(message: str) -> str | None:
    """Deterministic pre-route for thread-history questions.

    Returns the route token when the message asks about this conversation,
    or ``None`` to let the normal (LLM + keyword) routing proceed:
    "leave" for leave-scoped history questions, "recap" for generic ones.
    """
    if not is_history_question(message):
        return None
    lowered = message.lower()
    if any(word in lowered for word in _LEAVE_HISTORY_WORDS):
        return "leave"
    return "recap"


def make_recap_node(llm: LLM | None):
    """Summarize the current thread's transcript; no tools, no retrieval.

    With an LLM the summary is generated from the transcript; without one
    (or on a provider failure) the node serves the transcript itself so the
    chat never bounces on a recap question.
    """

    async def recap_node(state: SupervisorState, writer: StreamWriter) -> dict:
        query = state.get("current_query", "")
        async with trace_agent_turn(
            "recap",
            query=query,
            conversation_id=state.get("conversation_id"),
        ) as span:
            transcript = history_text(state.get("messages", []), max_tokens=2000)
            answer = f"{_FALLBACK_HEADER}\n{transcript}"
            if llm is not None:
                try:
                    raw = await llm.complete(
                        _RECAP_SYSTEM, f"CONVERSATION TRANSCRIPT:\n{transcript}\n\nSUMMARY:"
                    )
                    if raw and raw.strip():
                        answer = raw.strip()
                except Exception:  # noqa: BLE001 - the fallback answer is always safe
                    logger.warning("Recap: LLM summarization failed; serving the transcript", exc_info=True)
            writer({"type": "message", "text": answer})
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, answer)
            return {
                "messages": [AIMessage(content=answer)],
                "knowledge_result": None,
                "answer": answer,
                "citations": [],
                "confidence": 0.0,
                "agent": "recap",
                "safety": "PASS",
            }

    return recap_node

