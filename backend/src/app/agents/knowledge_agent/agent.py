"""Knowledge service agent: the node that answers from the knowledge base.

The agent is a thin orchestration layer over ``KnowledgeService`` (which
already owns hybrid retrieval, reranking, grounding, confidence gating, and
answer generation). Its added value here:

- *Query rewriting*: turning a context-dependent follow-up ("what about sick
  leave?") into a self-contained retrieval query using the conversation
  history.
- *Conversation-aware generation*: the answer prompt includes a compact
  history block, so answers can reference the thread.
- *Claim tracking*: the generation prompt requires ``[N]`` markers on every
  claim (the grounded context is already numbered 1..N in citation order);
  afterwards the agent parses the markers and keeps ONLY the citations the
  answer actually referenced — the persisted citations equal claims made.
- *Output safety*: the configured safety pipeline (evidence gate, citation
  coverage, PII, sensitive topics, optional judge) runs on the completed
  answer; blocks become honest refusals, and a flagged answer gets one
  repair pass with a strict citation prompt.

No ReAct tool loop for v1: the node calls the service directly. Tools stay
available for future multi-hop search needs, but they would add latency and
prompt fragility for no benefit today.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage

from app.agents.context import history_text
from app.agents.knowledge_agent.prompts import REPAIR_SYSTEM, REWRITE_SYSTEM
from app.knowledge.contracts import Citation, KnowledgeResult
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM
from app.safety.contracts import GuardVerdict, OutputContext
from app.safety.interfaces import ResponseGuard

_MARKER_RE = re.compile(r"\[(\d{1,3})\]")

_REFUSAL_PHRASES = (
    "i couldn't find enough evidence",
    "i don't know",
    "i do not know",
    "i cannot answer",
    "i can't answer",
    "not enough information",
    "insufficient information",
)

# The honest refusal used whenever the assistant must not answer: low
# confidence, empty evidence, or a BLOCK verdict from the safety pipeline.
REFUSAL_MESSAGE = (
    "I couldn't find enough evidence in the knowledge base to answer "
    "that confidently. Try rephrasing the question, or ask about a "
    "specific policy, procedure, or guideline."
)


@dataclass
class KnowledgeTurn:
    """One knowledge-agent turn: what was asked, what was searched, what resulted."""

    original_query: str
    rewritten_query: str
    result: KnowledgeResult
    answer: str | None


def verified_citations(text: str, citations: list[Citation]) -> list[Citation]:
    """The citations an answer actually references via ``[N]`` markers.

    This is the claim-tracking contract: only markers present in the text
    count, and only for indices within the retrieved set. Out-of-range
    markers (never-retrieved sources) are excluded.
    """
    markers = {int(m) for m in _MARKER_RE.findall(text)}
    if not markers:
        return []
    return [c for i, c in enumerate(citations, start=1) if i in markers]


def strip_invalid_markers(text: str, citation_count: int) -> str:
    """Remove ``[N]`` markers that reference sources never retrieved."""

    def _keep(match: re.Match[str]) -> str:
        return match.group(0) if int(match.group(1)) <= citation_count else ""

    return _MARKER_RE.sub(_keep, text)


def _is_refusal(text: str) -> bool:
    lowered = text.strip().lower()
    return any(phrase in lowered for phrase in _REFUSAL_PHRASES)


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


async def _repair_answer(
    llm: LLM | None,
    query: str,
    result: KnowledgeResult,
    history_block: str,
    draft: str,
) -> str | None:
    """One repair pass: regenerate the draft with mandatory ``[N]`` markers."""
    if llm is None:
        return None
    user = (
        f"CONVERSATION HISTORY:\n{history_block}\n\nQUESTION:\n{query}\n\n"
        f"GROUNDED CONTEXT:\n{result.grounded_context}\n\nDRAFT ANSWER:\n{draft}\n\n"
        "REWRITE (with [N] markers on every claim):"
    )
    try:
        return (await llm.complete(REPAIR_SYSTEM, user)).strip()
    except Exception:  # noqa: BLE001 - a failed repair keeps the draft
        return None


async def _track_and_guard(
    llm: LLM | None,
    query: str,
    result: KnowledgeResult,
    history_block: str,
    draft: str,
    guard: ResponseGuard | None,
) -> tuple[str, list[Citation], str]:
    """Apply output safety + claim tracking to the generated draft.

    Returns ``(final_text, verified_citations, safety_verdict)``.

    - BLOCK (e.g. evidence gate) -> the honest refusal, no citations.
    - REDACTED (e.g. PII) -> the redacted response.
    - FLAGGED (e.g. claims without markers) -> one repair pass with a strict
      citation prompt; falls back to the draft if the repair fails or the
      draft is a refusal.
    - Verified citations always come from the markers in the FINAL text.
    """
    verdict = GuardVerdict.PASS
    if guard is not None:
        guarded = await guard.guard(
            OutputContext(
                response=draft,
                grounded_context=result.grounded_context,
                citations=result.citations,
                confidence=result.confidence,
            )
        )
        verdict = guarded.verdict
        draft = guarded.response

    if verdict is GuardVerdict.BLOCKED:
        return REFUSAL_MESSAGE, [], GuardVerdict.BLOCKED.value

    if (
        verdict is GuardVerdict.FLAGGED_FOR_REVIEW
        and llm is not None
        and not _is_refusal(draft)
        and not verified_citations(draft, result.citations)
    ):
        repaired = await _repair_answer(llm, query, result, history_block, draft)
        if repaired and verified_citations(repaired, result.citations):
            draft = repaired
            if guard is not None:
                # Re-check the repaired answer: coverage now passes, so the
                # final verdict reflects the served text, not the draft.
                rechecked = await guard.guard(
                    OutputContext(
                        response=draft,
                        grounded_context=result.grounded_context,
                        citations=result.citations,
                        confidence=result.confidence,
                    )
                )
                verdict = rechecked.verdict

    # Never persist markers for sources that were never retrieved.
    final = strip_invalid_markers(draft, len(result.citations))
    return final, verified_citations(final, result.citations), verdict.value


async def stream_knowledge_turn(
    *,
    service: KnowledgeService,
    llm: LLM | None,
    query: str,
    history: list[BaseMessage],
    writer: Callable[[dict], None],
    guard: ResponseGuard | None = None,
    history_max_tokens: int = 800,
) -> dict:
    """Run one knowledge turn, streaming events through ``writer``.

    Events (dicts the chat layer forwards as SSE)::

        {"type": "retrieval", "rewritten_query": str, "result": KnowledgeResult}
        {"type": "token", "text": str}     # answer tokens, when generation runs
        {"type": "message", "text": str}   # honest refusal / grounded-context fallback

    Returns the state update for the supervisor graph: the final answer, the
    VERIFIED citations (only those the answer actually cited), confidence,
    agent, the safety verdict, and the final AIMessage.
    """
    rewritten = await rewrite_query(llm, query, history)
    result = await service.retrieve(rewritten)
    writer({"type": "retrieval", "rewritten_query": rewritten, "result": result})

    if result.low_confidence or not result.citations:
        message = fallback_message(KnowledgeTurn(query, rewritten, result, None))
        writer({"type": "message", "text": message})
        return {
            "messages": [AIMessage(content=message)],
            "knowledge_result": result,
            "answer": message,
            "citations": [],
            "confidence": result.confidence,
            "agent": "knowledge",
            "safety": GuardVerdict.PASS.value,
        }

    history_block = history_text(history, max_tokens=history_max_tokens)
    draft = ""
    async for token in service.stream_answer(rewritten, result, history=history_block):
        draft += token
        writer({"type": "token", "text": token})
    if not draft:
        # No generation LLM configured: serve the grounded context.
        draft = result.grounded_context or "(no grounded context)"
        writer({"type": "message", "text": draft})

    message, citations, safety = await _track_and_guard(
        llm, rewritten, result, history_block, draft, guard
    )

    return {
        "messages": [AIMessage(content=message)],
        "knowledge_result": result,
        "answer": message,
        "citations": citations,
        "confidence": result.confidence,
        "agent": "knowledge",
        "safety": safety,
    }


def fallback_message(turn: KnowledgeTurn) -> str:
    """The message text when no LLM answer is available.

    - Low confidence / no citations: honest refusal (never fabricate).
    - Evidence retrieved but no generation LLM configured: serve the grounded
      context, matching the search endpoint's ``answer=None`` fallback.
    """
    if turn.result.low_confidence or not turn.result.citations:
        return REFUSAL_MESSAGE
    return turn.result.grounded_context or "(no grounded context)"
