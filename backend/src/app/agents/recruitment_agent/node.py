"""Recruitment node — deterministic v1.

Answers the read paths (open vacancies, vacancy detail, my applications,
application lists) straight from the real ``RecruitmentService`` with no
model in the loop — the same deterministic-first discipline as the leave
agent. Write paths that need capabilities chat does not have (resume
upload for ``apply``, UUID-based hiring decisions) are deferred honestly to
the portal instead of pretending to act.

Upgrade path: swap this for the leave agent's JSON dispatch loop
(``ChatProvider.complete_json`` + tools + confirmation gate) once chat gains
file upload and a human-readable application reference scheme.
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from langchain_core.messages import AIMessage
from langgraph.types import StreamWriter

from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.contracts.auth import UserContext
from app.db.sync_session import SessionLocal

if TYPE_CHECKING:
    from app.agents.supervisor.state import SupervisorState

_DECISION_WORDS = ("approve", "reject", "shortlist", "decide", "interview")
_APPLY_WORDS = ("apply", "submit resume", "submit cv", "interested in")
_APPLICATION_VIEW_WORDS = ("application", "applications", "candidates", "applied")


def _vacancy_lines(vacancies: list) -> str:
    """One formatted line per vacancy."""
    lines = []
    for v in vacancies:
        line = f"- {v.title} ({v.employment_type})"
        if v.closing_date is not None:
            line += f", closing {v.closing_date.isoformat()}"
        if v.status != "OPEN":
            line += f" — {v.status}"
        lines.append(line)
    return "\n".join(lines)


def _application_lines(applications: list) -> str:
    """One formatted line per application."""
    return "\n".join(
        f"- {a.vacancy.title} — {a.application_status} (applied {a.applied_at:%Y-%m-%d})"
        for a in applications
    )


def _matched_vacancy_title(service: RecruitmentService, lowered: str) -> str | None:
    """The title of an open vacancy the message names, or None.

    Conservative exact-title substring match: "how do I apply for the data
    analyst job" matches the Data Analyst vacancy, while a generic "what jobs
    are open" matches nothing.
    """
    normalized = re.sub(r"[^a-z0-9 ]", "", lowered)
    matches = [v.title for v in service.list_vacancies(None) if v.title.lower() in normalized]
    return matches[0] if len(matches) == 1 else None


def _list_vacancies_reply(service: RecruitmentService) -> str:
    vacancies = service.list_vacancies(None)
    if not vacancies:
        return "There are no open vacancies right now. Check the Careers section later."
    return (
        "Open vacancies:\n"
        + _vacancy_lines(vacancies)
        + "\n\nAsk about a specific role, or use the Careers section to apply."
    )


def _vacancy_detail_reply(service: RecruitmentService, title: str) -> str:
    vacancies = service.list_vacancies(None)
    vacancy = next((v for v in vacancies if v.title.lower() == title.lower()), None)
    if vacancy is None:
        return f"I couldn't find an open vacancy called {title!r}."
    parts = [f"**{vacancy.title}** ({vacancy.employment_type})"]
    if vacancy.description:
        parts.append(vacancy.description)
    if vacancy.closing_date is not None:
        parts.append(f"Closes: {vacancy.closing_date.isoformat()}")
    parts.append("Apply through the Careers section of the portal.")
    return "\n\n".join(parts)


def _apply_reply(service: RecruitmentService, lowered: str) -> str:
    title = _matched_vacancy_title(service, lowered)
    if title is not None:
        return (
            f"To apply for the **{title}** role, please use the **Careers** section "
            "of the portal — applications need a resume upload, which chat can't "
            "accept yet."
        )
    vacancies = service.list_vacancies(None)
    if vacancies:
        return (
            "Applications need a resume upload, so they're handled in the **Careers** "
            "section of the portal — chat can't accept them yet.\n\n"
            "Open vacancies you can apply to there:\n"
            + _vacancy_lines(vacancies)
        )
    return (
        "Applications need a resume upload, so they're handled in the **Careers** "
        "section of the portal — chat can't accept them yet."
    )


def _is_my_applications(lowered: str, actor: UserContext | None) -> bool:
    """Is this candidate asking about THEIR OWN applications?"""
    if "my application" in lowered:
        return True
    if ("applied" in lowered or "application" in lowered) and "my" in lowered:
        return True
    return (
        actor is not None
        and actor.coarse_role == "CANDIDATE"
        and ("did i apply" in lowered or "have i applied" in lowered)
    )


def _my_applications_reply(actor: UserContext | None, service: RecruitmentService) -> str:
    if actor is None or actor.coarse_role != "CANDIDATE":
        return (
            "Only candidates can view their applications. If you're a manager, "
            "ask me to list the applications to review."
        )
    try:
        apps = service.list_my_applications(actor)
    except PermissionError_ as err:
        return str(err)
    if not apps:
        return "You haven't applied to any vacancies yet — ask me what's open!"
    return "Your applications:\n" + _application_lines(apps)


def _applications_reply(actor: UserContext | None, service: RecruitmentService, lowered: str) -> str:
    """Manager view: all applications, or those for a named vacancy."""
    title = _matched_vacancy_title(service, lowered)
    try:
        if title is not None:
            vacancy = next(
                (v for v in service.list_vacancies(actor) if v.title.lower() == title.lower()),
                None,
            )
            if vacancy is None:
                return f"I couldn't find a vacancy called {title!r}."
            apps = service.list_vacancy_applications(actor, vacancy.vacancy_id)
            if not apps:
                return f"No applications for {vacancy.title} yet."
            return f"Applications for {vacancy.title}:\n" + _application_lines(apps)
        apps = service.list_all_applications(actor)
    except PermissionError_ as err:
        return str(err)
    if not apps:
        return "There are no applications to review yet."
    return "All applications:\n" + _application_lines(apps)


def _help_reply(service: RecruitmentService) -> str:
    lines = [
        "Here's what I can help with on Recruitment:",
        "- what jobs are open",
        "- details about a specific role (e.g. \"tell me about the Data Analyst vacancy\")",
        "- my applications (candidates)",
        "- applications to review (managers)",
        "",
        "Applications are submitted through the **Careers** section of the portal.",
    ]
    vacancies = service.list_vacancies(None)
    if vacancies:
        lines.extend(["", "Open vacancies right now:", _vacancy_lines(vacancies)])
    return "\n".join(lines)


def _answer(actor: UserContext | None, service: RecruitmentService, user_message: str) -> str:
    """The deterministic reply for one recruitment message."""
    lowered = user_message.lower()

    if actor is not None and actor.coarse_role == "HR_ADMIN":
        if any(word in lowered for word in _DECISION_WORDS):
            return (
                "Hiring decisions are made in the manager portal — chat can't change an "
                "application's status yet. Here's what you can review here:\n"
                + _applications_reply(actor, service, lowered)
            )
        if any(word in lowered for word in _APPLICATION_VIEW_WORDS):
            return _applications_reply(actor, service, lowered)

    if _is_my_applications(lowered, actor):
        return _my_applications_reply(actor, service)

    if any(word in lowered for word in _APPLY_WORDS):
        return _apply_reply(service, lowered)

    title = _matched_vacancy_title(service, lowered)
    if title is not None:
        return _vacancy_detail_reply(service, title)

    if any(
        word in lowered
        for word in ("vacanc", "job", "jobs", "position", "positions", "open roles", "hiring", "careers", "recruit")
    ):
        return _list_vacancies_reply(service)

    return _help_reply(service)


def make_recruitment_node(
    *,
    actor: UserContext | None = None,
    service: RecruitmentService | None = None,
) -> Callable[[SupervisorState, StreamWriter], Awaitable[dict]]:
    """Build the recruitment node for the supervisor graph.

    ``service`` may be injected for tests; otherwise a request-scoped
    ``RecruitmentService`` is built on the sync session (the leave node's
    pattern). ``actor`` is the chat-layer user, resolved per request.
    """

    async def recruitment_node(state: SupervisorState, writer: StreamWriter) -> dict:
        if service is not None:
            reply = _answer(actor, service, state["current_query"])
        else:
            with SessionLocal() as db:
                reply = _answer(actor, RecruitmentService(db), state["current_query"])
        writer({"type": "message", "text": reply})
        return {
            "messages": [AIMessage(content=reply)],
            "knowledge_result": None,
            "answer": reply,
            "citations": [],
            "confidence": 0.0,
            "agent": "recruitment",
            "safety": "PASS",
        }

    return recruitment_node
