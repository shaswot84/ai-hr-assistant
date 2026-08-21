"""Recruitment Agent tools: service-backed wrappers and UI widget builders."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable
from typing import Any

from openinference.semconv.trace import SpanAttributes
from pydantic import BaseModel, ConfigDict, Field

from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.contracts.auth import UserContext
from app.domain.recruitment import Application, Vacancy
from app.observability import trace_tool_call


class ToolError(Exception):
    """A tool-level failure meant to be relayed to the user in plain language."""


async def _call_service(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    tool_name = getattr(fn, "__name__", "recruitment_tool")
    async with trace_tool_call(tool_name, parameters=kwargs) as span:
        try:
            res = await fn(*args, **kwargs)
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, str(res)[:1000])
            return res
        except (PermissionError_, ValueError) as err:
            span.set_attribute("tool.error", str(err))
            raise ToolError(str(err)) from err


# ---- Schemas -------------------------------------------------------------


class ListVacanciesArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetVacancyDetailArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(..., min_length=1)


class ListMyApplicationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ApplyToVacancyArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vacancy_title: str = Field(..., min_length=1)


class ListManagerApplicationsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vacancy_title: str | None = None


class WithdrawApplicationArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    vacancy_title: str | None = None
    application_id: str | None = None


# ---- Tool Implementations ------------------------------------------------


async def list_vacancies_tool(service: RecruitmentService, actor: UserContext | None) -> list[Vacancy]:
    return await _call_service(service.list_vacancies, actor)


async def get_vacancy_detail_tool(
    service: RecruitmentService, actor: UserContext | None, title: str
) -> Vacancy | None:
    vacancies = await list_vacancies_tool(service, actor)
    normalized = re.sub(r"[^a-z0-9 ]", "", title.lower())
    for v in vacancies:
        if v.title.lower() in normalized or normalized in v.title.lower():
            return v
    return None


async def list_my_applications_tool(
    service: RecruitmentService, actor: UserContext | None
) -> list[Application]:
    if actor is None or actor.coarse_role != "CANDIDATE":
        raise ToolError("Only candidates can view their applications.")
    return await _call_service(service.list_my_applications, actor)


async def withdraw_application_tool(
    service: RecruitmentService,
    actor: UserContext | None,
    vacancy_title: str | None = None,
    application_id: str | None = None,
) -> Application:
    if actor is None or actor.coarse_role != "CANDIDATE":
        raise ToolError("Only candidates can withdraw their applications.")

    if application_id:
        try:
            app_uuid = uuid.UUID(str(application_id))
        except (ValueError, TypeError) as err:
            raise ToolError(f"Invalid application id: {application_id}") from err
        return await _call_service(service.withdraw_application, actor, app_uuid)

    apps = await _call_service(service.list_my_applications, actor)
    withdrawable = [a for a in apps if a.application_status in ("APPLIED", "SHORTLISTED")]

    if vacancy_title:
        normalized = re.sub(r"[^a-z0-9 ]", "", vacancy_title.lower())
        matched = [
            a
            for a in withdrawable
            if a.vacancy
            and (
                re.sub(r"[^a-z0-9 ]", "", a.vacancy.title.lower()) in normalized
                or normalized in re.sub(r"[^a-z0-9 ]", "", a.vacancy.title.lower())
            )
        ]
        if not matched:
            raise ToolError(
                f"I couldn't find an active application for {vacancy_title!r} to withdraw."
            )
        if len(matched) > 1:
            raise ToolError(
                f"Multiple active applications match {vacancy_title!r}. Please be more specific."
            )
        return await _call_service(service.withdraw_application, actor, matched[0].application_id)

    if len(withdrawable) == 1:
        return await _call_service(service.withdraw_application, actor, withdrawable[0].application_id)
    if len(withdrawable) == 0:
        raise ToolError("You don't have any active applications to withdraw.")
    raise ToolError(
        "You have multiple active applications. Please specify which position you want to withdraw from."
    )


async def list_manager_applications_tool(
    service: RecruitmentService, actor: UserContext | None, vacancy_title: str | None = None
) -> list[Application]:
    if actor is None or actor.coarse_role != "HR_ADMIN":
        raise ToolError("Only managers can review applications.")
    if vacancy_title:
        vacancies = await _call_service(service.list_vacancies, actor)
        matched = next((v for v in vacancies if v.title.lower() == vacancy_title.lower()), None)
        if matched is None:
            raise ToolError(f"I couldn't find a vacancy called {vacancy_title!r}.")
        return await _call_service(service.list_vacancy_applications, actor, matched.vacancy_id)
    return await _call_service(service.list_all_applications, actor)


# ---- UI Widgets ----------------------------------------------------------


def vacancies_list_widget(vacancies: list[Vacancy]) -> dict[str, Any]:
    return {
        "type": "vacancies_list",
        "vacancies": [
            {
                "vacancy_id": str(getattr(v, "vacancy_id", "")),
                "title": getattr(v, "title", ""),
                "employment_type": getattr(v, "employment_type", ""),
                "department_name": getattr(getattr(v, "department", None), "name", ""),
                "description": getattr(v, "description", "") or "",
                "closing_date": (
                    v.closing_date.isoformat()
                    if getattr(v, "closing_date", None) is not None
                    else None
                ),
                "status": getattr(v, "status", "OPEN"),
            }
            for v in vacancies
        ],
    }


def vacancy_detail_widget(vacancy: Vacancy) -> dict[str, Any]:
    return {
        "type": "vacancy_detail",
        "vacancy": {
            "vacancy_id": str(getattr(vacancy, "vacancy_id", "")),
            "title": getattr(vacancy, "title", ""),
            "employment_type": getattr(vacancy, "employment_type", ""),
            "department_name": getattr(getattr(vacancy, "department", None), "name", ""),
            "description": getattr(vacancy, "description", "") or "",
            "closing_date": (
                vacancy.closing_date.isoformat()
                if getattr(vacancy, "closing_date", None) is not None
                else None
            ),
            "status": getattr(vacancy, "status", "OPEN"),
        },
    }


def apply_vacancy_widget(vacancy: Vacancy) -> dict[str, Any]:
    return {
        "type": "apply_vacancy",
        "vacancy_id": str(getattr(vacancy, "vacancy_id", "")),
        "vacancy_title": getattr(vacancy, "title", "Position"),
        "employment_type": getattr(vacancy, "employment_type", ""),
        "department_name": getattr(getattr(vacancy, "department", None), "name", ""),
        "closing_date": (
            vacancy.closing_date.isoformat()
            if getattr(vacancy, "closing_date", None) is not None
            else None
        ),
    }


def applications_list_widget(applications: list[Application]) -> dict[str, Any]:
    return {
        "type": "applications_list",
        "applications": [
            {
                "application_id": str(getattr(a, "application_id", uuid.uuid4())),
                "vacancy_id": str(
                    getattr(a, "vacancy_id", getattr(getattr(a, "vacancy", None), "vacancy_id", ""))
                ),
                "vacancy_title": (
                    getattr(a.vacancy, "title", "Role") if getattr(a, "vacancy", None) else "Role"
                ),
                "department_name": (
                    getattr(getattr(a.vacancy, "department", None), "name", "")
                    if getattr(a, "vacancy", None)
                    else ""
                ),
                "application_status": getattr(a, "application_status", "APPLIED"),
                "applied_at": (
                    a.applied_at.isoformat()
                    if getattr(a, "applied_at", None) is not None
                    else ""
                ),
            }
            for a in applications
        ],
    }


# ---- Formatting Helpers --------------------------------------------------


def vacancy_lines(vacancies: list[Vacancy]) -> str:
    lines = []
    for v in vacancies:
        line = f"- **{v.title}** ({v.employment_type})"
        if v.closing_date is not None:
            line += f", closing {v.closing_date.isoformat()}"
        if v.status != "OPEN":
            line += f" — {v.status}"
        lines.append(line)
    return "\n".join(lines)


def application_lines(applications: list[Application]) -> str:
    return "\n".join(
        f"- **{a.vacancy.title if a.vacancy else 'Role'}** — **{a.application_status}** (applied {a.applied_at:%Y-%m-%d})"
        for a in applications
    )


def format_vacancies_reply(vacancies: list[Vacancy]) -> str:
    if not vacancies:
        return "There are no open vacancies right now. Please check back later!"
    return (
        "Here are the currently available job vacancies:\n\n"
        + vacancy_lines(vacancies)
        + "\n\nYou can click **Apply** below or ask me about any specific role to get started!"
    )


def format_vacancy_detail_reply(vacancy: Vacancy) -> str:
    parts = [f"### **{vacancy.title}** ({vacancy.employment_type})"]
    if vacancy.description:
        parts.append(vacancy.description)
    if vacancy.closing_date is not None:
        parts.append(f"**Closing Date:** {vacancy.closing_date.isoformat()}")
    parts.append("You can apply directly below by uploading your resume.")
    return "\n\n".join(parts)


def format_my_applications_reply(applications: list[Application]) -> str:
    if not applications:
        return (
            "You haven't submitted any job applications yet.\n\n"
            "Ask me **'What jobs are open?'** to view current vacancies and apply!"
        )
    return "Here is the current status of your job applications:\n\n" + application_lines(applications)


def format_apply_reply(vacancy: Vacancy | None, all_vacancies: list[Vacancy]) -> str:
    if vacancy is not None:
        return (
            f"You can apply for the **{vacancy.title}** role directly here in chat! "
            "Please upload your resume (PDF or DOCX) in the form below to submit your application, "
            "or apply through the **Careers** section."
        )
    if all_vacancies:
        return (
            "Which role would you like to apply for? "
            "You can choose one of our open positions below to upload your resume directly, "
            "or explore them in the **Careers** section:\n\n"
            + vacancy_lines(all_vacancies)
        )
    return (
        "There are no open vacancies available for application at the moment. "
        "Please check back in the **Careers** section later!"
    )


def format_help_reply(vacancies: list[Vacancy]) -> str:
    lines = [
        "Here's what I can help you with on Recruitment:",
        "- **View Open Vacancies**: Ask *'What jobs are open?'* to explore available roles.",
        "- **Apply for Vacancies**: Ask *'How do I apply for [Job Title]?'* or click Apply to submit your resume directly.",
        "- **Check Application Status**: Ask *'What's the status of my application?'* to track your progress.",
        "- **Withdraw Application**: Ask *'Withdraw my application for [Job Title]'* to withdraw an active application.",
    ]
    if vacancies:
        lines.extend(["", "Currently open roles:", vacancy_lines(vacancies)])
    return "\n".join(lines)


# ---- Matching Helpers ----------------------------------------------------


async def find_matched_vacancy(service: RecruitmentService, user_message: str) -> Vacancy | None:
    lowered = user_message.lower()
    normalized = re.sub(r"[^a-z0-9 ]", "", lowered)
    vacancies = await service.list_vacancies(None)
    matches = [v for v in vacancies if v.title.lower() in normalized]
    if len(matches) == 1:
        return matches[0]
    # Try partial token overlap
    for v in vacancies:
        tokens = [t for t in v.title.lower().split() if len(t) > 2]
        if tokens and all(t in normalized for t in tokens):
            return v
    return None
