"""Intent routing: LLM classification with a keyword fallback.

The LLM decides the route from the current message plus conversation
context. When no LLM is configured, the call fails, or the model returns
something unparseable, ``heuristic_route`` takes over so the chat never
bounces on routing.
"""

from __future__ import annotations

import re

from langchain_core.messages import BaseMessage

from app.agents.context import history_text
from app.agents.supervisor.prompts import ROUTING_SYSTEM
from app.model_gateway.interfaces import LLM

ROUTES = ("knowledge", "leave", "recruitment", "clarify")

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


def heuristic_route(query: str) -> str:
    """Deterministic keyword routing; knowledge is the safe default."""
    lowered = query.lower()
    if any(keyword in lowered for keyword in _LEAVE_KEYWORDS):
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
    return _parse_route(raw) or heuristic_route(query)
