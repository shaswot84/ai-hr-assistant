"""Recruitment Agent orchestration: deterministic interception + LLM fallback."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from app.agents.recruitment_agent import prompts
from app.agents.recruitment_agent.state import RecruitmentAgentState
from app.agents.recruitment_agent.tools import (
    ToolError,
    applications_list_widget,
    apply_vacancy_widget,
    find_matched_vacancy,
    format_apply_reply,
    format_help_reply,
    format_my_applications_reply,
    format_vacancies_reply,
    format_vacancy_detail_reply,
    get_vacancy_detail_tool,
    list_manager_applications_tool,
    list_my_applications_tool,
    list_vacancies_tool,
    vacancies_list_widget,
    vacancy_detail_widget,
)
from app.capabilities.recruitment import RecruitmentService
from app.contracts.auth import UserContext
from app.model_gateway.provider import ChatProvider, ChatProviderError
from app.shared.clock import Clock, get_clock

logger = logging.getLogger(__name__)

_FALLBACK_UNAVAILABLE = "Sorry, I'm having trouble connecting right now — please try again shortly."
_DECISION_WORDS = ("approve", "reject", "shortlist", "decide", "interview")
_APPLY_WORDS = ("apply", "submit resume", "submit cv", "upload resume", "upload cv", "interested in", "send resume")
_STATUS_WORDS = ("status", "progress", "shortlisted", "update on my", "check my", "did i get", "have i been")
_VACANCY_WORDS = ("vacanc", "job", "jobs", "position", "positions", "open roles", "hiring", "careers", "recruit")


@dataclass(frozen=True)
class AgentTurnResult:
    """What one call to handle_turn produces for the chat/supervisor layer."""

    reply: str
    tool_called: str | None = None
    tool_result: dict[str, Any] | None = None
    raw_model_action: dict[str, Any] | None = None
    ui_widget: dict[str, Any] | None = None


def _is_status_query(lowered: str, actor: UserContext | None) -> bool:
    if "my application" in lowered or "my applications" in lowered:
        return True
    if any(word in lowered for word in _STATUS_WORDS) and ("application" in lowered or "applied" in lowered or "role" in lowered or "job" in lowered):
        return True
    if actor is not None and actor.coarse_role == "CANDIDATE":
        if any(phrase in lowered for phrase in ("did i apply", "have i applied", "my status", "application status")):
            return True
    return False


async def handle_turn(
    *,
    actor: UserContext | None,
    state: RecruitmentAgentState | None,
    service: RecruitmentService,
    chat_provider: ChatProvider | None,
    user_message: str,
    clock: Clock | None = None,
) -> AgentTurnResult:
    clock = clock or get_clock()
    lowered = user_message.lower()

    if state is not None:
        state.add_turn("user", user_message, clock=clock)

    # 1. HR Admin manager paths
    if actor is not None and actor.coarse_role == "HR_ADMIN":
        if any(word in lowered for word in _DECISION_WORDS):
            try:
                apps = list_manager_applications_tool(service, actor)
                reply = (
                    "Hiring decisions are made in the manager portal. Here are the applications you can review:\n\n"
                    + format_my_applications_reply(apps)
                )
                widget = applications_list_widget(apps) if apps else None
            except ToolError as err:
                reply = str(err)
                widget = None
            if state is not None:
                state.add_turn("agent", reply, clock=clock)
            return AgentTurnResult(reply=reply, ui_widget=widget)

        if "candidate" in lowered or "who applied" in lowered or "review application" in lowered:
            matched_v = find_matched_vacancy(service, user_message)
            v_title = matched_v.title if matched_v else None
            try:
                apps = list_manager_applications_tool(service, actor, v_title)
                reply = (
                    f"Applications for **{v_title}**:\n\n" if v_title else "All applications for review:\n\n"
                ) + (format_my_applications_reply(apps) if apps else "No applications found.")
                widget = applications_list_widget(apps) if apps else None
            except ToolError as err:
                reply = str(err)
                widget = None
            if state is not None:
                state.add_turn("agent", reply, clock=clock)
            return AgentTurnResult(reply=reply, ui_widget=widget)

    # 2. Candidate / user application status check
    if _is_status_query(lowered, actor):
        try:
            apps = list_my_applications_tool(service, actor)
            reply = format_my_applications_reply(apps)
            widget = applications_list_widget(apps) if apps else None
        except ToolError as err:
            reply = str(err)
            widget = None
        if state is not None:
            state.add_turn("agent", reply, clock=clock)
        return AgentTurnResult(reply=reply, ui_widget=widget)

    # 3. Apply for vacancies path
    if any(word in lowered for word in _APPLY_WORDS):
        matched_v = find_matched_vacancy(service, user_message)
        all_open = list_vacancies_tool(service, actor)
        if matched_v is not None:
            reply = format_apply_reply(matched_v, all_open)
            widget = apply_vacancy_widget(matched_v)
        else:
            reply = format_apply_reply(None, all_open)
            widget = vacancies_list_widget(all_open) if all_open else None
        if state is not None:
            state.add_turn("agent", reply, clock=clock)
        return AgentTurnResult(reply=reply, ui_widget=widget)

    # 4. Specific Vacancy Detail
    matched_v = find_matched_vacancy(service, user_message)
    if matched_v is not None:
        reply = format_vacancy_detail_reply(matched_v)
        widget = apply_vacancy_widget(matched_v)
        if state is not None:
            state.add_turn("agent", reply, clock=clock)
        return AgentTurnResult(reply=reply, ui_widget=widget)

    # 5. List open vacancies
    if any(word in lowered for word in _VACANCY_WORDS):
        vacancies = list_vacancies_tool(service, actor)
        reply = format_vacancies_reply(vacancies)
        widget = vacancies_list_widget(vacancies) if vacancies else None
        if state is not None:
            state.add_turn("agent", reply, clock=clock)
        return AgentTurnResult(reply=reply, ui_widget=widget)

    # 6. LLM dispatch fallback if chat_provider is configured
    if chat_provider is not None:
        try:
            system_prompt = prompts.build_system_prompt()
            turn_prompt = prompts.build_turn_prompt(
                user_message,
                history=state.history_for_prompt() if state else None,
                user_role=actor.coarse_role if actor else None,
            )
            raw = await chat_provider.complete_json(
                system_prompt=system_prompt,
                user_prompt=turn_prompt,
                temperature=0.0,
            )
            if isinstance(raw, dict):
                action = raw.get("action")
                if action == "reply" and raw.get("reply"):
                    reply = str(raw["reply"])
                    if state is not None:
                        state.add_turn("agent", reply, clock=clock)
                    return AgentTurnResult(reply=reply, raw_model_action=raw)
                if action == "call_tool":
                    tool = raw.get("tool")
                    args = raw.get("args", {})
                    if tool == "list_vacancies":
                        vacancies = list_vacancies_tool(service, actor)
                        reply = format_vacancies_reply(vacancies)
                        widget = vacancies_list_widget(vacancies) if vacancies else None
                        return AgentTurnResult(reply=reply, tool_called=tool, raw_model_action=raw, ui_widget=widget)
                    if tool == "get_vacancy_detail":
                        title = args.get("title", "")
                        v = get_vacancy_detail_tool(service, actor, title)
                        if v:
                            reply = format_vacancy_detail_reply(v)
                            widget = apply_vacancy_widget(v)
                        else:
                            reply = f"I couldn't find an open vacancy for {title!r}."
                            widget = None
                        return AgentTurnResult(reply=reply, tool_called=tool, raw_model_action=raw, ui_widget=widget)
                    if tool == "list_my_applications":
                        try:
                            apps = list_my_applications_tool(service, actor)
                            reply = format_my_applications_reply(apps)
                            widget = applications_list_widget(apps) if apps else None
                        except ToolError as err:
                            reply = str(err)
                            widget = None
                        return AgentTurnResult(reply=reply, tool_called=tool, raw_model_action=raw, ui_widget=widget)
        except ChatProviderError:
            logger.exception("Recruitment Agent: chat provider call failed")

    # 7. Default help reply
    vacancies = list_vacancies_tool(service, actor)
    reply = format_help_reply(vacancies)
    widget = vacancies_list_widget(vacancies) if vacancies else None
    if state is not None:
        state.add_turn("agent", reply, clock=clock)
    return AgentTurnResult(reply=reply, ui_widget=widget)
