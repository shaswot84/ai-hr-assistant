"""Intent routing: LLM classification with a keyword fallback.

The LLM decides the route from the current message plus conversation
context. When no LLM is configured, the call fails, or the model returns
something unparseable, ``heuristic_route`` takes over so the chat never
bounces on routing. A deterministic knowledge override also guards the LLM
path: clearly knowledge-framed leave questions (policy / definition
wording) are re-routed to knowledge even when the model says "leave", so
the LLM path and the fallback agree on the knowledge-vs-leave boundary.
"""

from __future__ import annotations

import re

from langchain_core.messages import BaseMessage

from app.agents.context import history_text
from app.agents.supervisor.prompts import ROUTING_SYSTEM
from app.model_gateway.interfaces import LLM

ROUTES = ("knowledge", "leave", "recruitment", "clarify")

# Knowledge-base framing words. When present (and not outweighed by explicit
# transactional framing) a message that also mentions leave is a POLICY
# question for the knowledge agent (RAG over HR documents), not a
# transactional leave-agent question — the leave agent has no retrieval path
# and cannot answer "what is the annual leave policy?".
_KNOWLEDGE_POLICY_WORDS = frozenset(
    {
        "policy",
        "policies",
        "procedure",
        "procedures",
        "guideline",
        "guidelines",
        "rule",
        "rules",
        "regulation",
        "regulations",
        "accrual",
        "accrue",
        "accrues",
        "accrued",
        "entitlement",
        "entitlements",
        "entitled",
        "eligib",  # eligible / eligibility
        "explain",
        "definition",
        "meaning",
    }
)

# Transactional framing that overrides the policy check: balance/request
# wording makes a message about the caller's own leave ACTIONS, never a
# policy read ("my annual leave balance" is leave, not knowledge).
_TRANSACTIONAL_OVERRIDE_WORDS = frozenset(
    {"balance", "remaining", "left", "request", "requests"}
)

# Definition framing: "what is X?" / "how does X work?" about a leave type is
# a knowledge question (the KB defines it), not a transaction. Guarded by
# possessive/transactional framing so "what is MY balance" stays on leave.
_DEFINITION_PHRASES = (
    "what is",
    "what's",
    "what are",
    "what does",
    "what do",
    "meaning of",
    "definition of",
    "how does",
    "how is",
    "how are",
)
_DEFINITION_GUARD_WORDS = frozenset(
    {
        "my",
        "balance",
        "remaining",
        "left",
        "request",
        "requests",
        "apply",
        "book",
        "take",
        "avail",
        "get",
        "submit",
        "cancel",
        "approve",
        "reject",
        "how much",
        "do i have",
    }
)


# Heuristic fallback keywords. "leave" is checked first so an ambiguous
# "how do I apply for leave?" routes to leave, not recruitment.
_LEAVE_KEYWORDS = frozenset(
    {
        "annual leave",
        "sick leave",
        "casual leave",
        "leave balance",
        "time off",
        "day off",
        "leave request",
        "leave",
        "leaves",
        "vacation",
        "holiday",
        "holidays",
        "pto",
        "absence",
        "absences",
    }
)
_RECRUITMENT_KEYWORDS = frozenset(
    {
        "vacancy",
        "vacancies",
        "job",
        "jobs",
        "apply",
        "application",
        "applications",
        "hiring",
        "interview",
        "interviews",
        "resume",
        "resumes",
        "cv",
        "career",
        "careers",
        "candidate",
        "recruitment",
        "offer letter",
    }
)

_ROUTE_RE = re.compile(r"\b(knowledge|leave|recruitment|clarify)\b")


def _is_knowledge_policy_question(lowered: str) -> bool:
    """Is this message a leave-policy question for the knowledge agent?

    Policy vocabulary ("policy", "accrual", "entitled", ...) marks a
    knowledge-base question; explicit transactional vocabulary (balance,
    request) marks the leave agent and wins.
    """
    if any(word in lowered for word in _TRANSACTIONAL_OVERRIDE_WORDS):
        return False
    return any(word in lowered for word in _KNOWLEDGE_POLICY_WORDS)


def _is_knowledge_definition_question(lowered: str) -> bool:
    """Is this a definition/explanation question about leave itself?

    "what is annual leave?" / "how does sick leave work?" are knowledge
    questions — the KB defines the leave types. Personal/transactional
    framing ("what is MY balance", "what is a leave request") keeps the
    question on the leave agent.
    """
    if any(word in lowered for word in _DEFINITION_GUARD_WORDS):
        return False
    return any(phrase in lowered for phrase in _DEFINITION_PHRASES)


def heuristic_route(query: str) -> str:
    """Deterministic keyword routing; knowledge is the safe default.

    Leave-policy and leave-definition questions ("what is the annual leave
    policy?", "what is annual leave?") are routed to knowledge BEFORE the
    leave keywords: the knowledge agent is the one with retrieval over HR
    documents, while the leave agent is transactional (balance / requests /
    cancel) and cannot answer them.
    """
    lowered = query.lower()
    if _is_knowledge_policy_question(lowered):
        return "knowledge"
    if any(keyword in lowered for keyword in _LEAVE_KEYWORDS):
        if _is_knowledge_definition_question(lowered):
            return "knowledge"
        return "leave"
    if any(keyword in lowered for keyword in _RECRUITMENT_KEYWORDS):
        return "recruitment"
    return "knowledge"


def _parse_route(raw: str) -> str | None:
    """Extract a route token from the model's reply, tolerating noise."""
    token = raw.strip().lower().strip(".,!?;:'\"")
    if token in ROUTES:
        return token
    match = _ROUTE_RE.search(raw.lower())
    return match.group(1) if match else None


async def route_intent(llm: LLM | None, query: str, history: list[BaseMessage]) -> str:
    """Classify the current message into one of the four routes.

    Falls back to :func:`heuristic_route` when the LLM is unavailable or its
    reply cannot be parsed — routing must never raise.
    """
    if llm is None:
        return heuristic_route(query)
    user = (
        f"CONVERSATION HISTORY:\n{history_text(history)}\n\n"
        f"CURRENT USER MESSAGE: {query}\nROUTE:"
    )
    try:
        raw = await llm.complete(ROUTING_SYSTEM, user)
    except Exception:  # noqa: BLE001 - routing never fails because of the LLM
        return heuristic_route(query)
    route = _parse_route(raw) or heuristic_route(query)
    # Deterministic override on the LLM path: a clearly knowledge-framed
    # leave question (policy / definition wording) reaches the knowledge
    # agent even when the model misclassifies it as leave, so the LLM path
    # and the heuristic fallback agree on the boundary.
    lowered = query.lower()
    if route == "leave" and (
        _is_knowledge_policy_question(lowered)
        or _is_knowledge_definition_question(lowered)
    ):
        return "knowledge"
    return route
