"""Knowledge service agent: the node that answers from the knowledge base.

The agent is a thin orchestration layer over ``KnowledgeService`` (which
already owns hybrid retrieval, reranking, grounding, confidence gating, and
answer generation). Its only added value here is *query rewriting*: turning
a context-dependent follow-up ("what about sick leave?") into a
self-contained retrieval query using the conversation history — exactly the
multi-turn problem that motivated durable history in the first place.

No ReAct tool loop for v1: the node calls the service directly. Tools stay
available for future multi-hop search needs, but they would add latency and
prompt fragility for no benefit today.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage

from app.agents.context import history_text
from app.agents.knowledge_agent.prompts import REWRITE_SYSTEM
from app.knowledge.contracts import KnowledgeResult
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM


@dataclass
class KnowledgeTurn:
    """One knowledge-agent turn: what was asked, what was searched, what resulted."""

    original_query: str
    rewritten_query: str
    result: KnowledgeResult
    answer: str | None


async def rewrite_query(llm: LLM | None, query: str, history: list[BaseMessage]) -> str:
    """Make the retrieval query self-contained using conversation context.

    Falls back to the raw query when no LLM is configured or rewriting
    fails — retrieval must never fail because of the rewrite step.
    """
    if llm is None:
        return query
    user = f"CONVERSATION HISTORY:\n{history_text(history)}\n\nQUESTION: {query}\n\nREWRITTEN QUERY:"
    try:
        rewritten = (await llm.complete(REWRITE_SYSTEM, user)).strip()
        return rewritten or query
    except Exception:  # noqa: BLE001 - retrieval never fails because of rewriting
        return query


async def stream_knowledge_turn(
    *,
    service: KnowledgeService,
    llm: LLM | None,
    query: str,
    history: list[BaseMessage],
    writer: Callable[[dict], None],
) -> dict:
    """Run one knowledge turn, streaming events through ``writer``.

    Events (dicts the chat layer forwards as SSE)::

        {"type": "retrieval", "rewritten_query": str, "result": KnowledgeResult}
        {"type": "token", "text": str}     # answer tokens, when generation runs
        {"type": "message", "text": str}   # honest refusal / grounded-context fallback

    Returns the state update for the supervisor graph (answer, citations,
    confidence, agent, and the final AIMessage).
    """
    rewritten = await rewrite_query(llm, query, history)
    result = await service.retrieve(rewritten)
    writer({"type": "retrieval", "rewritten_query": rewritten, "result": result})

    if result.low_confidence or not result.citations:
        message = fallback_message(KnowledgeTurn(query, rewritten, result, None))
        writer({"type": "message", "text": message})
    else:
        message = ""
        async for token in service.stream_answer(rewritten, result):
            message += token
            writer({"type": "token", "text": token})
        if not message:
            # No generation LLM configured: serve the grounded context.
            message = result.grounded_context or "(no grounded context)"
            writer({"type": "message", "text": message})

    return {
        "messages": [AIMessage(content=message)],
        "knowledge_result": result,
        "answer": message,
        "citations": result.citations,
        "confidence": result.confidence,
        "agent": "knowledge",
    }


def fallback_message(turn: KnowledgeTurn) -> str:
    """The message text when no LLM answer is available.

    - Low confidence / no citations: honest refusal (never fabricate).
    - Evidence retrieved but no generation LLM configured: serve the grounded
      context, matching the search endpoint's ``answer=None`` fallback.
    """
    if turn.result.low_confidence or not turn.result.citations:
        return (
            "I couldn't find enough evidence in the knowledge base to answer "
            "that confidently. Try rephrasing the question, or ask about a "
            "specific policy, procedure, or guideline."
        )
    return turn.result.grounded_context or "(no grounded context)"
