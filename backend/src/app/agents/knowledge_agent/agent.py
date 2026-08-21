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
- *Balance reconciliation*: for balance-relevant employee questions, the
  real leave balance is fetched from the leave system and appended to the
  policy answer deterministically (see ``_employee_balance_block``) — the
  policy number and the employee's actual remaining days travel together.

No ReAct tool loop for v1: the node calls the service directly. Tools stay
available for future multi-hop search needs, but they would add latency and
prompt fragility for no benefit today.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.messages import AIMessage, BaseMessage
from openinference.semconv.trace import OpenInferenceSpanKindValues, SpanAttributes

from app.agents.context import history_text
from app.agents.knowledge_agent.genui import generate_knowledge_genui
from app.agents.knowledge_agent.prompts import REPAIR_SYSTEM, REWRITE_SYSTEM
from app.agents.leave_agent.tools import (
    ToolError,
    format_tool_result,
    get_leave_balance,
    mentioned_leave_type,
)
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.knowledge.access import access_roles_for
from app.knowledge.contracts import Citation, KnowledgeResult
from app.knowledge.markers import parse_marker_set, renumber_markers
from app.knowledge.service import KnowledgeService
from app.model_gateway.interfaces import LLM
from app.observability import async_trace_span, trace_agent_turn
from app.safety.contracts import GuardVerdict, OutputContext
from app.safety.interfaces import ResponseGuard

_REFUSAL_PHRASES = (
    "i couldn't find enough evidence",
    "i don't know",
    "i do not know",
    "i cannot answer",
    "i can't answer",
    "not enough information",
    "insufficient information",
)

# ---- current-balance enrichment (policy + real balance reconciliation) ----
#
# "how many sick days do I get" is answered from the policy docs (entitlement
# numbers), but the employee's ACTUAL remaining balance lives in the leave
# system. On a balance-relevant employee question the real balance is fetched
# from the leave service and both (a) injected into the generation context
# and (b) appended to the final answer deterministically — formatted exactly
# like the leave agent's own balance reply, so the two agents never disagree
# about numbers.

_BALANCE_LEAVE_WORDS = (
    "leave",
    "balance",
    "time off",
    "days off",
    "vacation",
    "holiday",
    "holidays",
    "pto",
    "absence",
    "absences",
    "sick days",
)
_BALANCE_ASK_PHRASES = (
    "how many",
    "how much",
    "balance",
    "remaining",
    "left",
    "entitled",
    "entitlement",
    "available",
    "do i have",
    "do i get",
    "days do i",
    "get",
)

# Label used when the balance is injected into the generation context: it is
# authoritative for numbers but NOT part of the citation set — the LLM must
# never attach [N] markers to balance numbers (they are not retrieved
# evidence), or the claim-tracking pass would flag them.
_BALANCE_PROMPT_LABEL = (
    "CURRENT LEAVE BALANCE (authoritative, from the leave system — NOT part "
    "of the citation set; never attach [N] markers to balance numbers):"
)


def balance_relevant(query: str) -> bool:
    """Is this query about leave amounts the employee actually has?

    Balance/entitlement phrasing ("how many", "how much", "balance",
    "remaining", "entitled", ...) combined with leave vocabulary marks a
    question where the employee's real balance is a useful, authoritative
    addition to the policy answer. Purely definitional or procedural
    questions ("what is the carryover policy?", "when can I take leave?") do
    not qualify.
    """
    lowered = query.lower()
    if not any(word in lowered for word in _BALANCE_LEAVE_WORDS):
        return False
    return any(phrase in lowered for phrase in _BALANCE_ASK_PHRASES)


async def _employee_balance_block(
    actor: UserContext | None,
    leave_service: LeaveService | None,
    query: str,
) -> str | None:
    """The employee's real leave balance as a plain-text block, or None.

    Only for EMPLOYEE actors on balance-relevant queries; any failure (no
    balance rows, role gate, service error) yields None — the policy answer
    is never held hostage to the balance lookup.
    """
    if actor is None or leave_service is None or actor.coarse_role != "EMPLOYEE":
        return None
    if not balance_relevant(query):
        return None
    try:
        mentioned = await mentioned_leave_type(leave_service, query)
        result = await get_leave_balance(leave_service, actor, leave_type_name=mentioned)
    except ToolError:
        return None
    if not result:
        return None
    return format_tool_result("get_leave_balance", result)



# The honest refusal used whenever the assistant must not answer: low
# confidence, empty evidence, or a BLOCK verdict from the safety pipeline.
REFUSAL_MESSAGE = (
    "I couldn't find enough evidence in the knowledge base to answer "
    "that confidently. Try rephrasing the question, or ask about a "
    "specific policy, procedure, or guideline."
)

# Deterministic reply when the knowledge base has no INDEXED documents at
# all — distinct from a low-confidence refusal so an empty system never
# reads as a retrieval failure.
EMPTY_KB_MESSAGE = (
    "The knowledge base is empty — no documents have been uploaded yet. "
    "Ask an HR admin to upload policies, procedures, or guidelines, and "
    "I can answer questions from them."
)


def denied_message(result: KnowledgeResult) -> str:
    """Deterministic access-denial reply for restricted matches.

    The query hit document(s) the requester cannot access; the reply names
    the allowlist roles of the matched documents (identity only — never the
    content) so the user knows the file exists but is out of their reach.
    """
    roles = sorted({role for doc in result.restricted for role in doc.allowed_roles})
    role_label = ", ".join(roles) if roles else "HR_ADMIN"
    return f"You cannot access this file. Only {role_label} can see it."


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
    markers = parse_marker_set(text)
    if not markers:
        return []
    return [c for i, c in enumerate(citations, start=1) if i in markers]


def _is_refusal(text: str) -> bool:
    lowered = text.strip().lower()
    return any(phrase in lowered for phrase in _REFUSAL_PHRASES)


async def rewrite_query(llm: LLM | None, query: str, history: list[BaseMessage]) -> str:
    """Make the retrieval query self-contained using conversation context.

    Falls back to the raw query when no LLM is configured or rewriting
    fails — retrieval must never fail because of the rewrite step.
    """
    async with async_trace_span(
        "knowledge_agent.rewrite_query",
        span_kind=OpenInferenceSpanKindValues.CHAIN,
        attributes={SpanAttributes.INPUT_VALUE: query},
    ) as span:
        if llm is None:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, query)
            return query
        user = f"CONVERSATION HISTORY:\n{history_text(history)}\n\nQUESTION: {query}\n\nREWRITTEN QUERY:"
        try:
            rewritten = (await llm.complete(REWRITE_SYSTEM, user)).strip()
            res = rewritten or query
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, res)
            return res
        except Exception:  # noqa: BLE001 - retrieval never fails because of rewriting
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, query)
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

    # Persist markers ONLY for citations the answer actually cited, and
    # renumber them densely (1..k) so marker N always indexes the k-th served
    # citation — never a chunk that was retrieved but not cited.
    verified = verified_citations(draft, result.citations)
    keep = [i for i, c in enumerate(result.citations, start=1) if c in verified]
    final = renumber_markers(draft, keep)
    return final, verified, verdict.value


async def stream_knowledge_turn(
    *,
    service: KnowledgeService,
    llm: LLM | None,
    query: str,
    history: list[BaseMessage],
    writer: Callable[[dict], None],
    guard: ResponseGuard | None = None,
    history_max_tokens: int = 800,
    actor: UserContext | None = None,
    leave_service: LeaveService | None = None,
) -> dict:
    """Run one knowledge turn, streaming events through ``writer``.

    Events (dicts the chat layer forwards as SSE)::

        {"type": "retrieval", "rewritten_query": str, "result": KnowledgeResult}
        {"type": "token", "text": str}     # answer tokens, when generation runs
        {"type": "message", "text": str}   # honest refusal / grounded-context fallback

    Returns the state update for the supervisor graph: the final answer, the
    VERIFIED citations (only those the answer actually cited), confidence,
    agent, the safety verdict, and the final AIMessage.

    ``actor`` + ``leave_service`` enable balance reconciliation: on a
    balance-relevant employee question the real balance is appended to the
    policy answer deterministically (and injected into the generation
    context) — see ``_employee_balance_block``.
    """
    async with trace_agent_turn(
        "knowledge",
        query=query,
        user_id=actor.subject if actor else None,
    ) as agent_span:
        rewritten = await rewrite_query(llm, query, history)
        result = await service.retrieve(rewritten, access_roles=access_roles_for(actor))
        writer({"type": "retrieval", "rewritten_query": rewritten, "result": result})

        if result.empty_knowledge_base:
            # No documents indexed at all: deterministic "empty knowledge base"
            # reply, never a connection-looking failure.
            message = EMPTY_KB_MESSAGE
            writer({"type": "message", "text": message})
            agent_span.set_attribute(SpanAttributes.OUTPUT_VALUE, message)
            return {
                "messages": [AIMessage(content=message)],
                "knowledge_result": result,
                "answer": message,
                "citations": [],
                "confidence": result.confidence,
                "agent": "knowledge",
                "safety": GuardVerdict.PASS.value,
            }

        if result.restricted:
            # The query matched only documents the requester cannot access:
            # reply with a deterministic denial naming the allowed roles.
            message = denied_message(result)
            writer({"type": "message", "text": message})
            agent_span.set_attribute(SpanAttributes.OUTPUT_VALUE, message)
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
        balance_block = await _employee_balance_block(actor, leave_service, query)
        if balance_block:
            history_block = f"{history_block}\n\n{_BALANCE_PROMPT_LABEL}\n{balance_block}"

        if result.low_confidence or not result.citations:
            message = fallback_message(KnowledgeTurn(query, rewritten, result, None))
            if balance_block:
                # No policy evidence, but the real balance is still a true answer
                # to the balance half of the question — append it to the refusal.
                message = f"{message}\n\n{balance_block}"
            writer({"type": "message", "text": message})
            agent_span.set_attribute(SpanAttributes.OUTPUT_VALUE, message)
            return {
                "messages": [AIMessage(content=message)],
                "knowledge_result": result,
                "answer": message,
                "citations": [],
                "confidence": result.confidence,
                "agent": "knowledge",
                "safety": GuardVerdict.PASS.value,
            }

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
        if balance_block:
            # Deterministic reconciliation: the policy answer above, the real
            # balance below — formatted exactly like the leave agent's reply.
            message = f"{message}\n\n{balance_block}"

        agent_span.set_attribute(SpanAttributes.OUTPUT_VALUE, message)
        agent_span.set_attribute("agent.citations_count", len(citations))
        agent_span.set_attribute("agent.confidence", float(result.confidence))
        agent_span.set_attribute("agent.safety", safety)

        ui_widget = None
        if llm is not None and not _is_refusal(message) and safety != GuardVerdict.BLOCKED.value:
            ui_widget = await generate_knowledge_genui(
                llm=llm,
                query=query,
                answer=message,
                grounded_context=result.grounded_context,
                actor=actor,
            )
            if ui_widget:
                writer({"type": "ui_widget", "widget": ui_widget})

        return {
            "messages": [AIMessage(content=message)],
            "knowledge_result": result,
            "answer": message,
            "citations": citations,
            "confidence": result.confidence,
            "agent": "knowledge",
            "safety": safety,
            "ui_widget": ui_widget,
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
