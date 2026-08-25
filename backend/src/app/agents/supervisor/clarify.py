"""Clarify node: handles ambiguous, off-topic, greeting, and farewell messages.

The node is role-aware: each user role sees only the capabilities relevant
to them.  Off-topic messages (ice cream, weather, etc.) receive a generic
decline; greetings and farewells get friendly replies instead of the
clarification prompt.
"""

from __future__ import annotations

import re

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from openinference.semconv.trace import SpanAttributes

from app.agents.supervisor.state import SupervisorState
from app.contracts.auth import UserContext
from app.observability import trace_agent_turn

# ── Role-specific capability lists ────────────────────────────────────

_ROLE_CAPABILITIES: dict[str, list[tuple[str, str]]] = {
    "HR_ADMIN": [
        ("Company policy & knowledge", "HR policy, procedures, guidelines, benefits"),
        ("Leave management", "view all requests, approve/reject, team balances"),
        ("Recruitment", "review applications, manage vacancies, hiring decisions"),
    ],
    "EMPLOYEE": [
        ("Company policy & knowledge", "HR policy, procedures, guidelines, benefits"),
        ("Leave", "balances, submit requests, cancel requests, team calendar"),
    ],
    "CANDIDATE": [
        ("Company policy & knowledge", "HR policy, procedures, guidelines"),
        ("Recruitment", "browse vacancies, apply, check application status"),
    ],
}

_VISITOR_CAPABILITIES: list[tuple[str, str]] = [
    ("Company policy & knowledge", "HR policy, procedures, guidelines"),
    ("Recruitment", "browse open vacancies"),
]

# ── Off-topic detection keywords ──────────────────────────────────────
# If the user's message contains NONE of these, it is off-topic.

_HR_KEYWORDS = frozenset(
    {
        # leave
        "annual leave", "sick leave", "casual leave", "leave balance",
        "leave request", "leave", "leaves", "vacation", "holiday",
        "holidays", "company holiday", "time off", "day off", "out of office",
        "team calendar", "half day", "half-day", "pto", "absence", "absences",
        # recruitment
        "vacancy", "vacancies", "job", "jobs", "apply", "application",
        "applications", "hiring", "interview", "interviews", "resume",
        "resumes", "cv", "career", "careers", "candidate", "recruitment",
        "offer letter",
        # general HR
        "policy", "policies", "procedure", "guidelines", "employee",
        "benefits", "salary", "compensation", "training", "onboarding",
        "payroll", "dress code", "handbook", "compliance", "performance",
        "appraisal", "bonus", "insurance", "health", "wellness",
        "work from home", "remote work", "flextime", "overtime",
        "resignation", "termination", "notice period", "probation",
        "headcount", "org chart", "department", "team",
    },
)


def _is_off_topic(query: str) -> bool:
    """Return True when the query has no HR-related content."""
    lowered = query.lower()
    return not any(kw in lowered for kw in _HR_KEYWORDS)


# ── Greeting / farewell detection ─────────────────────────────────────

_GREETING_RE = re.compile(
    r"^\s*(hi+|hello+|hey+|howdy|greetings|good\s*(morning|afternoon|evening|day)|"
    r"(hi|hello)\s+(there|again|everyone|all))\b[\s!.]*$",
    re.IGNORECASE,
)
_FAREWELL_RE = re.compile(
    r"^\s*((bye|goodbye|good\s*bye|bye[- ]?bye|see\s*(ya|you)(\s+later|\s+soon)?)|"
    r"(thanks?|thank\s*you)(\s+(you|so\s+much|a\s+lot|very\s+much))?|that'?s\s+all)"
    r"\b[\s!,.]*$",
    re.IGNORECASE,
)


def _is_greeting(query: str) -> bool:
    """Return True when the query is a bare greeting ("hi", "good morning")."""
    return _GREETING_RE.match(query.strip()) is not None


def _is_farewell(query: str) -> bool:
    """Return True when the query is a farewell/thanks ("bye", "thanks")."""
    return _FAREWELL_RE.match(query.strip()) is not None


def _format_capabilities(role: str | None) -> str:
    """Build the bulleted capability list for a given role."""
    caps = _ROLE_CAPABILITIES.get(role, _VISITOR_CAPABILITIES)
    lines = [f"- **{name}** — {desc}" for name, desc in caps]
    return "\n".join(lines)


# ── Message templates ─────────────────────────────────────────────────

def _greeting_message(role: str | None) -> str:
    """Friendly welcome listing what the assistant can do for this role."""
    caps = _format_capabilities(role)
    return "Hello! How can I help you today?\n\nI can assist you with:\n\n" + caps


def _farewell_message(role: str | None) -> str:
    """Warm sign-off."""
    return (
        "You're welcome! Feel free to come back anytime you need help with "
        "HR questions, leave, or recruitment. Have a great day!"
    )


def _off_topic_message(query: str, role: str | None) -> str:
    """Generic decline for messages unrelated to HR."""
    caps = _format_capabilities(role)
    return (
        "I'm sorry, I can't help with that. "
        "Please contact the relevant department for assistance.\n\n"
        "I can assist you with:\n\n" + caps
    )


def _ambiguous_message(role: str | None) -> str:
    """Standard clarification prompt listing what the assistant can do."""
    caps = _format_capabilities(role)
    return (
        "Could you clarify what you'd like help with? "
        "I can assist with:\n\n" + caps + "\n\n"
        'For example: "What is the annual leave policy?" or '
        '"How do I apply for the Data Analyst vacancy?"'
    )


def _fallback_message(hint: str, role: str | None) -> str:
    """Subagent could not handle the request; show hint + capabilities."""
    caps = _format_capabilities(role)
    return (
        f"{hint}\n\n"
        "Could you please clarify what you'd like help with? "
        "I can assist with:\n\n" + caps
    )


# ── Node factory ──────────────────────────────────────────────────────

def make_clarify_node(actor: UserContext | None = None):
    """Build the clarify node, optionally bound to an authenticated user."""

    async def clarify_node(state: SupervisorState, writer: StreamWriter) -> dict:
        hint = state.get("clarification_hint")
        role = state.get("actor_role") or (actor.coarse_role if actor else None)
        query = state.get("current_query", "")
        clar_type = state.get("clarification_type")

        # Determine clarification type when not explicitly set.
        if clar_type is None:
            if hint:
                clar_type = "subagent_fallback"
            elif _is_greeting(query):
                clar_type = "greeting"
            elif _is_farewell(query):
                clar_type = "farewell"
            elif _is_off_topic(query):
                clar_type = "off_topic"
            else:
                clar_type = "ambiguous"

        # Build the response message.
        if clar_type == "greeting":
            message = _greeting_message(role)
        elif clar_type == "farewell":
            message = _farewell_message(role)
        elif clar_type == "off_topic":
            message = _off_topic_message(query, role)
        elif hint:
            message = _fallback_message(hint, role)
        else:
            message = _ambiguous_message(role)

        writer({"type": "message", "text": message})

        async with trace_agent_turn(
            "clarify",
            query=query,
            conversation_id=state.get("conversation_id"),
            user_id=actor.subject if actor else None,
        ) as span:
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, message)
            span.set_attribute("clarify.type", clar_type)

            return {
                "messages": [AIMessage(content=message)],
                "knowledge_result": None,
                "answer": message,
                "citations": [],
                "confidence": 0.0,
                "agent": "clarify",
                "can_handle": True,
                "clarification_hint": None,
                "actor_role": role,
                "clarification_type": clar_type,
            }

    return clarify_node
