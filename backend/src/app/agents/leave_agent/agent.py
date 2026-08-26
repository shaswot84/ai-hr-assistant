"""Leave Agent orchestration: one turn in, one reply out.

Hand-rolled dispatch loop over ChatProvider.complete_json — no
LangGraph/framework. This matches evaluation/scoring.py's existing
pattern and fits this codebase's actual constraints: the chat model is
manager-editable at runtime, so nothing here can assume the live model
supports native function-calling. Everything is driven by a plain
"respond with this JSON shape" contract, enforced by code, not by asking
the model nicely.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.agents.context import is_history_question
from app.agents.leave_agent import prompts
from app.agents.leave_agent.dates import extract_dates, extract_half_day_info, format_short, resolve_end_date
from app.agents.leave_agent.state import DraftRequest, LeaveAgentState
from app.agents.leave_agent.tools import (
    TOOLS,
    ToolError,
    canonical_args,
    format_tool_result,
    get_employee_leave_balance,
    get_leave_balance,
    get_team_out_of_office,
    hr_pending_request_lines,
    list_all_employee_balances,
    list_company_holidays,
    list_leave_requests,
    list_leave_types,
    list_my_leave_requests,
    mentioned_leave_type,
    pending_request_lines,
    preflight_cancel,
    preflight_hr_reference,
    preflight_submit,
    validate_args,
)
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.model_gateway.provider import ChatProvider, ChatProviderError
from app.shared.clock import Clock, get_clock

logger = logging.getLogger(__name__)

_FALLBACK_UNAVAILABLE = "Sorry, I'm having trouble right now — please try again shortly."
_FALLBACK_UNPARSEABLE = "Sorry, I didn't quite catch that — could you rephrase?"
_FALLBACK_ALREADY_RUNNING = "I'm already processing that — one moment."
_FALLBACK_EXPIRED = "That confirmation has expired — could you tell me again what you'd like to do?"
_FALLBACK_NO_MATCH = "I don't have that staged to confirm — could you tell me again what you'd like to do?"

_VALID_ACTIONS = {"reply", "stage", "call_tool"}


@dataclass(frozen=True)
class AgentTurnResult:
    """What one call to handle_turn produces, for the route layer to return."""

    reply: str
    tool_called: str | None = None
    tool_result: dict[str, Any] | None = None
    # The model's raw parsed JSON response for this turn, for observability
    # (matches the AI-observability fields audit_log already has room for:
    # model_version, prompt_version, latency_ms, token_usage). None only
    # when the provider call itself failed before returning anything.
    raw_model_action: dict[str, Any] | None = None
    ui_widget: dict[str, Any] | None = None


def _staged_action_widget(tool_name: str, args: dict, summary: str) -> dict[str, Any]:
    if tool_name == "submit_leave_request":
        return {
            "type": "staged_action",
            "action_type": "submit_leave",
            "title": "Confirm Leave Request",
            "tool": tool_name,
            "args": args,
            "summary": summary,
            "confirm_text": "Confirm & Submit",
            "cancel_text": "Cancel Draft",
        }
    elif tool_name == "cancel_leave_request":
        return {
            "type": "staged_action",
            "action_type": "cancel_leave",
            "title": "Confirm Leave Cancellation",
            "tool": tool_name,
            "args": args,
            "summary": summary,
            "confirm_text": f"Cancel {args.get('request_number', 'Request')}",
            "cancel_text": "Keep Request",
        }
    elif tool_name == "decide_leave_request":
        approve = args.get("approve", True)
        verb = "Approve" if approve else "Reject"
        return {
            "type": "staged_action",
            "action_type": "decide_leave",
            "title": f"Confirm Decision ({verb})",
            "tool": tool_name,
            "args": args,
            "summary": summary,
            "confirm_text": f"{verb} {args.get('request_number', 'Request')}",
            "cancel_text": "Dismiss",
        }
    return {
        "type": "staged_action",
        "action_type": "generic",
        "title": "Confirm Action",
        "tool": tool_name,
        "args": args,
        "summary": summary,
        "confirm_text": "Confirm",
        "cancel_text": "Cancel",
    }


def _action_result_widget(tool_name: str, result: Any) -> dict[str, Any]:
    return {
        "type": "action_result",
        "tool": tool_name,
        "result": result,
    }


def _leave_balance_widget(
    result: list[dict],
    year: int | None = None,
    employee_code: str | None = None,
    employee_name: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "leave_balance",
        "balances": result,
        "year": year,
        "employee_code": employee_code,
        "employee_name": employee_name,
    }


def _leave_requests_widget(result: list[dict], is_manager: bool = False) -> dict[str, Any]:
    return {
        "type": "leave_requests_list",
        "requests": result,
        "is_manager": is_manager,
    }


def _leave_types_widget(result: list[dict]) -> dict[str, Any]:
    return {
        "type": "leave_types_list",
        "types": result,
    }


def _leave_date_picker_widget(draft: DraftRequest, today: date | None = None) -> dict[str, Any]:
    return {
        "type": "leave_date_picker",
        "leave_type_name": draft.leave_type_name,
        "start_date": draft.start_date.isoformat() if draft.start_date else None,
        "end_date": draft.end_date.isoformat() if draft.end_date else None,
        "is_half_day": draft.is_half_day,
        "half_day_period": draft.half_day_period,
        "min_date": today.isoformat() if today else None,
    }


async def handle_turn(
    *,
    actor: UserContext,
    state: LeaveAgentState,
    service: LeaveService,
    chat_provider: ChatProvider,
    user_message: str,
    clock: Clock | None = None,
) -> AgentTurnResult:
    """Process one employee message and return the agent's reply.

    `state` is mutated in place — the caller (the route) persists it back
    into the SessionStore.

    The deterministic date interception runs FIRST: when the employee's
    message contains resolvable dates (or continues an in-progress draft),
    the turn is answered without the model — the model is never asked to
    understand "tomorrow".
    """
    clock = clock or get_clock()

    intercepted = await _intercept_list_requests(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = await _intercept_holidays_question(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = await _intercept_team_calendar_question(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = await _intercept_types_question(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = await _intercept_draft_turn(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = await _intercept_reference_writes(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted


    system_prompt = prompts.build_system_prompt()
    turn_prompt = prompts.build_turn_prompt(
        user_message,
        role=actor.coarse_role,
        history=state.history_for_prompt(),
        pending_confirmation=state.pending_for_prompt(),
        draft=state.draft_for_prompt(),
    )

    try:
        raw = await chat_provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=turn_prompt,
            temperature=0.0,  # low — this is a routing/extraction task, not creative writing
        )
    except ChatProviderError:
        logger.exception("Leave Agent: chat provider call failed")
        state.add_turn("employee", user_message, clock=clock)
        return _reply(state, _FALLBACK_UNAVAILABLE, clock=clock)

    state.add_turn("employee", user_message, clock=clock)

    parsed = _validate_response(raw)
    if parsed is None:
        logger.warning("Leave Agent: model response failed schema validation: %r", raw)
        return _reply(state, _FALLBACK_UNPARSEABLE, clock=clock, raw_model_action=raw)

    action, model_reply, tool_name, raw_args = parsed

    if action == "reply":
        return _reply(state, model_reply, clock=clock, raw_model_action=raw)

    if tool_name is None:
        logger.warning("Leave Agent: action %r without a tool name", action)
        return _reply(state, _FALLBACK_UNPARSEABLE, clock=clock, raw_model_action=raw)

    if action == "stage":
        return await _handle_stage(
            state, service, actor, tool_name, raw_args, clock=clock, raw_model_action=raw
        )

    # action == "call_tool"
    spec = TOOLS.get(tool_name)
    if spec is None:
        logger.warning("Leave Agent: model called unknown tool %r", tool_name)
        return _reply(state, _FALLBACK_UNPARSEABLE, clock=clock, raw_model_action=raw)

    if spec.requires_confirmation:
        return await _handle_confirmed_write(
            state, service, actor, tool_name, raw_args, clock=clock, raw_model_action=raw
        )

    return await _handle_read(
        state, service, actor, tool_name, raw_args, clock=clock,
        raw_model_action=raw, model_reply=model_reply, user_message=user_message,
    )


# ---- per-branch handlers (kept small and separate so each failure mode is
#      one clearly named function, not a long if/elif chain repeating the
#      same "record turn + build result" plumbing) --------------------------


def _reply(
    state: LeaveAgentState,
    text: str,
    *,
    clock: Clock,
    tool_called: str | None = None,
    tool_result: dict[str, Any] | None = None,
    raw_model_action: dict[str, Any] | None = None,
    ui_widget: dict[str, Any] | None = None,
) -> AgentTurnResult:
    """Record the agent's turn and build the result — the one place this
    "append history, then return" pairing happens, instead of repeated
    inline at every call site."""
    state.add_turn("agent", text, clock=clock)
    return AgentTurnResult(
        reply=text,
        tool_called=tool_called,
        tool_result=tool_result,
        raw_model_action=raw_model_action,
        ui_widget=ui_widget,
    )


# ---- deterministic list flows (requests / leave types) --------------------
#
# "show my leave requests" and "which leave types can I request" are answered
# from the REAL data without the model: the near-identical list tools
# (list_my_leave_requests vs list_leave_requests) and the type list are never
# left to the model to pick between, and these flows keep working even when
# the chat model is unreachable.

_LIST_MY_REQUESTS_PHRASES = (
    "my request",
    "my requests",
    "my leave request",
    "my leave requests",
    "my pending",
    "my history",
)
_HR_LIST_REQUESTS_PHRASES = (
    "all leave request",
    "all leave requests",
    "all request",
    "all requests",
    "leave request",
    "leave requests",
    "show all requests",
    "list all requests",
    "pending leave",
    "pending requests",
    "pipeline",
)
_TYPES_QUESTION_PHRASES = ("leave type", "types of leave", "which leaves", "what leaves")


def _is_list_my_requests(user_message: str) -> bool:
    """Is this employee message asking to SEE their own leave requests?"""
    lowered = user_message.lower()
    has_request_scope = any(phrase in lowered for phrase in _LIST_MY_REQUESTS_PHRASES)
    has_write_intent = (
        any(word in lowered for word in _CANCEL_INTENT_WORDS)
        or any(word in lowered for word in _DECIDE_INTENT_WORDS)
        or "approve" in lowered
    )
    return has_request_scope and not has_write_intent


_ALL_BALANCES_PHRASES = (
    "all employee",
    "all employees",
    "all the employee",
    "all the employees",
    "employees leave balance",
    "employees leave balances",
    "employees balance",
    "employees balances",
    "team balance",
    "team balances",
    "team leave balance",
    "team leave balances",
    "everyone's balance",
    "everybody's balance",
    "all balances",
    "org chart",
    "organization chart",
    "hierarchy",
    "org hierarchy",
    "organization hierarchy",
    "team hierarchy",
    "employee hierarchy",
    "reporting structure",
)


def _is_all_employees_balance_ask(user_message: str) -> bool:
    """Is this manager message asking to see all employees' leave balances or org hierarchy?"""
    lowered = user_message.lower()
    if any(h in lowered for h in ("hierarchy", "org chart", "organization chart", "reporting structure")):
        return True
    if not any(word in lowered for word in ("balance", "balances", "quota", "quotas", "pto", "remaining")):
        return False
    if "request" in lowered:
        return False
    return any(phrase in lowered for phrase in _ALL_BALANCES_PHRASES) or ("all" in lowered and "employee" in lowered)


def _is_list_hr_requests(user_message: str) -> bool:
    """Is this manager message asking to SEE all leave requests in the pipeline?"""
    lowered = user_message.lower()
    if "pending" in lowered or "balance" in lowered:
        return False
    has_request_scope = (
        any(phrase in lowered for phrase in _HR_LIST_REQUESTS_PHRASES)
        or ("request" in lowered and ("show" in lowered or "list" in lowered or "all" in lowered))
    )
    has_write_intent = (
        any(word in lowered for word in _CANCEL_INTENT_WORDS)
        or any(word in lowered for word in _DECIDE_INTENT_WORDS)
        or "approve" in lowered
    )
    return has_request_scope and not has_write_intent


def _is_types_question(user_message: str) -> bool:
    """Is this a direct question about which leave types EXIST?

    A listing ask ("which leave types can I request?") — not a request start
    ("i want to apply for annual leave") and not a definition question
    ("what is annual leave?"). The "leave type(s)" wording is specific
    enough that a bare request start never matches.
    """
    lowered = user_message.lower()
    mentions_types = any(phrase in lowered for phrase in _TYPES_QUESTION_PHRASES)
    # A request start naming a specific type is not a types question; only
    # an explicitly ask-for-the-list framing counts ("which/what/list/
    # available/are").
    request_start_without_listing = _is_request_intent(lowered) and not any(
        word in lowered for word in ("which", "what", "list", "available", "are")
    )
    return mentions_types and not request_start_without_listing


async def _intercept_list_requests(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer "show leave requests" or all-employee balances deterministically from the real data."""
    if actor.coarse_role == "HR_ADMIN":
        if _is_all_employees_balance_ask(user_message):
            try:
                result = await list_all_employee_balances(service, actor)
            except ToolError as err:
                return _reply(state, str(err), clock=clock)
            text = format_tool_result("list_all_employee_balances", result)
            return _reply(
                state, text, clock=clock,
                tool_called="list_all_employee_balances", tool_result=result,
                ui_widget={"type": "all_employee_balances", "employees": result, "year": clock.today().year},
            )

        if not _is_list_hr_requests(user_message):
            return None
        try:
            result = await list_leave_requests(service, actor)
        except ToolError as err:
            return _reply(state, str(err), clock=clock)
        text = format_tool_result("list_leave_requests", result)
        return _reply(
            state, text, clock=clock,
            tool_called="list_leave_requests", tool_result=result,
            ui_widget=_leave_requests_widget(result, is_manager=True),
        )

    if actor.coarse_role == "EMPLOYEE":
        if not _is_list_my_requests(user_message):
            return None
        try:
            result = await list_my_leave_requests(service, actor)
        except ToolError as err:
            return _reply(state, str(err), clock=clock)
        text = format_tool_result("list_my_leave_requests", result)
        return _reply(
            state, text, clock=clock,
            tool_called="list_my_leave_requests", tool_result=result,
            ui_widget=_leave_requests_widget(result, is_manager=False),
        )
    return None


async def _intercept_holidays_question(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer questions about company holidays / office closures deterministically."""
    lowered = user_message.lower()
    holiday_phrases = (
        "company holiday",
        "company holidays",
        "public holiday",
        "public holidays",
        "office closure",
        "office closures",
        "official holiday",
        "official holidays",
        "holiday calendar",
        "holidays this year",
        "upcoming holidays",
        "next holiday",
    )
    if not any(phrase in lowered for phrase in holiday_phrases):
        return None
    try:
        result = await list_company_holidays(service, actor)
    except ToolError as err:
        return _reply(state, str(err), clock=clock)
    text = format_tool_result("list_company_holidays", result)
    return _reply(
        state,
        text,
        clock=clock,
        tool_called="list_company_holidays",
        tool_result=result,
        ui_widget={"type": "company_holidays", "holidays": result},
    )


async def _intercept_team_calendar_question(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer questions about team out of office / absences deterministically."""
    lowered = user_message.lower()
    team_phrases = (
        "who is out of office",
        "who is off today",
        "who is on leave",
        "who is away",
        "team out of office",
        "team calendar",
        "team absence",
        "team absences",
        "department leave",
        "out of office",
    )
    if not any(phrase in lowered for phrase in team_phrases):
        return None
    try:
        result = await get_team_out_of_office(service, actor)
    except ToolError as err:
        return _reply(state, str(err), clock=clock)
    text = format_tool_result("get_team_out_of_office", result)
    return _reply(
        state,
        text,
        clock=clock,
        tool_called="get_team_out_of_office",
        tool_result=result,
        ui_widget={"type": "team_out_of_office", "entries": result},
    )


async def _intercept_types_question(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer "which leave types can I request?" deterministically."""
    if actor.coarse_role != "EMPLOYEE":
        return None
    if not _is_types_question(user_message):
        return None
    try:
        result = await list_leave_types(service, actor)
    except ToolError as err:
        return _reply(state, str(err), clock=clock)
    text = format_tool_result("list_leave_types", result)
    return _reply(
        state, text, clock=clock,
        tool_called="list_leave_types", tool_result=result,
        ui_widget=_leave_types_widget(result),
    )



# ---- deterministic request-draft flow -------------------------------------
#
# The model is not trusted with dates. These functions resolve relative
# dates ("tomorrow", "next monday", "for 3 days") against the Clock, hold
# the partial request in state.draft, and stage the confirmation
# deterministically the moment the draft is complete. The model's only
# remaining job in this flow is recognizing a yes/no on the staged action.

_DRAFT_CANCEL_WORDS = (
    "never mind",
    "nevermind",
    "forget it",
    "forget that",
    "scratch that",
    "cancel that",
    "drop it",
    "on second thought",
    "scratch it",
    "forget about it",
    "never mind that",
)


# ---- deterministic conversation-recap flow ---------------------------------
#
# "what leave did i apply above?" / "what did we discuss?" are answered from
# the thread's OWN history + workflow state — never from the DB. A recap is
# about THIS conversation: what was said here, the in-progress draft, and
# any staged action awaiting confirmation. The model's
# list_my_leave_requests remains the all-history DB view; this interception
# never calls a tool.

_RECAP_MAX_TURNS = 6
_RECAP_LINE_LIMIT = 160


def _recap_reply(state: LeaveAgentState, *, clock: Clock) -> AgentTurnResult:
    """A deterministic recap of this thread: recent turns + workflow state.

    Built entirely from ``state`` (history, draft, pending confirmation) —
    no DB access, no tools, no model. The transcript tail is the truth
    about what was said here; the workflow facts are the truth about what
    is still in flight.
    """
    if not state.history and state.draft is None and state.pending_confirmation is None:
        return _reply(
            state, "We haven't discussed anything in this chat yet — how can I help?", clock=clock
        )

    lines: list[str] = ["Here's what we've discussed in this chat:"]
    for turn in state.history[-_RECAP_MAX_TURNS:]:
        speaker = "You" if turn.role == "employee" else "Assistant"
        content = turn.content.strip()
        if len(content) > _RECAP_LINE_LIMIT:
            content = content[:_RECAP_LINE_LIMIT] + "…"
        lines.append(f"- {speaker}: {content}")

    if state.pending_confirmation is not None:
        lines.append(f"Awaiting your confirmation: {state.pending_confirmation.summary}")
    if state.draft is not None:
        parts = [state.draft.leave_type_name or "leave request"]
        if state.draft.start_date is not None:
            parts.append(f"starting {format_short(state.draft.start_date)}")
        if state.draft.end_date is not None:
            parts.append(f"to {format_short(state.draft.end_date)}")
        lines.append(f"In progress: {' '.join(parts)} — not submitted yet.")

    return _reply(state, "\n".join(lines), clock=clock)


def _draft_canonical(draft: DraftRequest) -> dict:
    """Draft -> the JSON-safe canonical args shape of submit_leave_request,
    matching tools.canonical_args (mode="json") so the staged-vs-confirmed
    equality check in _handle_confirmed_write works unchanged."""
    return {
        "leave_type_name": draft.leave_type_name,
        "start_date": draft.start_date.isoformat(),
        "end_date": draft.end_date.isoformat() if draft.end_date else draft.start_date.isoformat(),
        "is_half_day": draft.is_half_day,
        "half_day_period": draft.half_day_period,
        "reason": draft.reason,
    }


async def _stage_draft(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    draft: DraftRequest,
    *,
    clock: Clock,
) -> AgentTurnResult:
    """Preflight + stage a completed draft deterministically."""
    canonical = _draft_canonical(draft)
    try:
        preflight_args = validate_args("submit_leave_request", canonical)
        working_days, holidays_in_range = await preflight_submit(
            service,
            actor,
            leave_type_name=preflight_args["leave_type_name"],
            start_date=preflight_args["start_date"],
            end_date=preflight_args["end_date"],
            is_half_day=preflight_args.get("is_half_day", False),
            half_day_period=preflight_args.get("half_day_period"),
        )
    except ToolError as err:
        return _reply(state, str(err), clock=clock)

    summary = prompts.summarize_for_confirmation(
        "submit_leave_request",
        canonical,
        working_days=working_days,
        holidays=holidays_in_range,
    )
    state.stage("submit_leave_request", canonical, summary, clock=clock)
    state.clear_draft(clock=clock)
    return _reply(
        state, summary, clock=clock,
        ui_widget=_staged_action_widget("submit_leave_request", canonical, summary),
    )


_BALANCE_ASK_WORDS = ("balance", "remaining", "left", "how much", "do i have")

# Possessive leave-noun phrases that read as balance asks when no request
# wording is present: "show my pto" / "my time off" are balance asks, while
# "can I book my time off" / "I want to use my annual leave" stay requests.
_BALANCE_POSSESSIVE_PHRASES = (
    "my leave",
    "my pto",
    "my time off",
    "my vacation",
    "my holiday",
    "my annual leave",
    "my sick leave",
    "my casual leave",
    "my unpaid leave",
)


def _is_balance_ask(user_message: str) -> bool:
    """Is this employee message asking for their OWN leave balance?"""
    lowered = user_message.lower()
    if "request" in lowered:
        return False
    if "someone else" in lowered or "another" in lowered or "other employee" in lowered or "their" in lowered:
        return False
    if any(word in lowered for word in _BALANCE_ASK_WORDS):
        return True
    if any(phrase in lowered for phrase in _BALANCE_POSSESSIVE_PHRASES):
        request_wording = any(
            word in lowered for word in _REQUEST_INTENT_WORDS if word != "get"
        )
        return not request_wording
    return "get" in lowered and "my leave" in lowered


_EMP_CODE_RE = re.compile(r"EMP-[A-Z0-9-]+|\bEMP-\d+\b", re.IGNORECASE)


def _extract_employee_lookup_target(user_message: str) -> str | None:
    """Extract an employee code or name from a manager's balance inquiry."""
    match = _EMP_CODE_RE.search(user_message)
    if match:
        return match.group(0).upper()
    lowered = user_message.lower().strip()
    if not any(w in lowered for w in ("balance", "remaining", "quota", "pto", "leave", "how much", "how many")):
        return None
    if any(p in lowered for p in ("all employee", "all the employee", "everyone", "team balance", "org chart", "hierarchy")):
        return None

    # Pattern: "John's balance", "John Doe's leave balance"
    possessive_match = re.search(r"\b([A-Z][a-zA-Z]*(?:\s+[A-Z][a-zA-Z]*)*)'s\s+(?:leave\s+)?(?:balance|quota|pto|days)", user_message)
    if possessive_match:
        return possessive_match.group(1).strip()

    # Pattern: "how much leave does <name> have", "how many days does <name> have"
    does_match = re.search(r"does\s+(?:employee\s+)?([A-Za-z]+(?:\s+[A-Za-z]+)*)\s+have", user_message, re.IGNORECASE)
    if does_match:
        return does_match.group(1).strip()

    if " for " in lowered:
        idx = lowered.find(" for ")
        target = user_message[idx + 5:].strip().rstrip(".?!\"'")
        if target.lower().startswith("employee "):
            target = target[9:].strip()
        target = re.sub(r"\s+(?:balance|quota|pto|in\s+\d{4})$", "", target, flags=re.IGNORECASE).strip()
        if target:
            return target

    if " of " in lowered:
        idx = lowered.find(" of ")
        target = user_message[idx + 4:].strip().rstrip(".?!\"'")
        if target.lower().startswith("employee "):
            target = target[9:].strip()
        target = re.sub(r"\s+(?:balance|quota|pto|in\s+\d{4})$", "", target, flags=re.IGNORECASE).strip()
        if target:
            return target

    if "employee " in lowered:
        idx = lowered.find("employee ")
        target = user_message[idx + 9:].strip().rstrip(".?!\"'")
        target = re.sub(r"\s+(?:balance|quota|pto|in\s+\d{4})$", "", target, flags=re.IGNORECASE).strip()
        if target:
            return target
    return None


async def _intercept_draft_turn(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer a date-bearing or draft-continuing turn WITHOUT the model."""
    lowered = user_message.lower().strip()

    if state.draft is not None and any(word in lowered for word in _DRAFT_CANCEL_WORDS):
        state.clear_draft(clock=clock)
        state.clear_pending(clock=clock)
        return _reply(
            state,
            "Alright, I've dropped that draft request. Let me know if you'd like to start again.",
            clock=clock,
        )

    if any(word in lowered for word in _CANCEL_INTENT_WORDS) or any(
        word in lowered for word in _DECIDE_INTENT_WORDS
    ) or "approve" in lowered:
        return None

    if is_history_question(user_message):
        return _recap_reply(state, clock=clock)

    # HR admins have no self-service leave. This check must run BEFORE the
    # no-draft early-return below, so "can I apply for leave?" (request
    # intent, no dates) is answered deterministically instead of falling
    # through to the model. Manager-scope phrasings ("show all requests",
    # "any pending requests?") are excluded — they belong to the manager
    # tools/listing flows, not the employee draft flow.
    if (
        actor.coarse_role == "HR_ADMIN"
        and _is_request_intent(user_message)
        and not _is_manager_scope_ask(user_message.lower())
    ):
        return _reply(
            state,
            "As an HR administrator you can review employees' leave requests "
            "and approve, reject, or cancel them — but you can't apply for "
            "leave yourself.",
            clock=clock,
        )

    today = clock.today()
    if actor.coarse_role == "EMPLOYEE" and _is_balance_ask(user_message):
        mentioned = await mentioned_leave_type(service, user_message)
        try:
            result = await get_leave_balance(service, actor, leave_type_name=mentioned)
        except ToolError as err:
            return _reply(state, str(err), clock=clock)
        text = format_tool_result("get_leave_balance", result)
        return _reply(
            state, text, clock=clock,
            tool_called="get_leave_balance", tool_result=result,
            ui_widget=_leave_balance_widget(result, year=today.year),
        )

    if actor.coarse_role == "HR_ADMIN":
        target = _extract_employee_lookup_target(user_message)
        if target:
            try:
                result = await get_employee_leave_balance(service, actor, employee_code=target, year=today.year)
                text = format_tool_result("get_employee_leave_balance", result)
                emp_name = result[0].get("employee_name") if result else None
                emp_code = result[0].get("employee_code") if result else target
                return _reply(
                    state,
                    text,
                    clock=clock,
                    tool_called="get_employee_leave_balance",
                    tool_result=result,
                    ui_widget=_leave_balance_widget(
                        result,
                        year=today.year,
                        employee_code=emp_code,
                        employee_name=emp_name,
                    ),
                )
            except ToolError as err:
                return _reply(
                    state,
                    str(err),
                    clock=clock,
                    tool_called="get_employee_leave_balance",
                )


    start, end = extract_dates(user_message, today)
    is_half, period = extract_half_day_info(user_message)

    draft = state.draft
    if draft is None:
        if not _is_request_intent(user_message) or start is None:
            return None
        draft = DraftRequest()

    if is_half:
        draft.is_half_day = True
        draft.half_day_period = period or "MORNING"
        if start is not None:
            draft.start_date = start
            draft.end_date = start

    if start is None and end is None and state.draft is not None and state.draft.start_date is not None:
        end = resolve_end_date(user_message, state.draft.start_date, today)
    elif start is not None and end is None and state.draft is not None and state.draft.start_date is not None:
        if start >= state.draft.start_date:
            end = start
            start = None

    had_type = draft.leave_type_name is not None
    if draft.leave_type_name is None:
        mentioned = await mentioned_leave_type(service, user_message)
        if mentioned is not None:
            draft.leave_type_name = mentioned

    progress = start is not None or end is not None
    if not had_type and draft.leave_type_name is not None:
        progress = True
    if not progress:
        return None

    if start is not None:
        draft.start_date = start
    if end is not None:
        draft.end_date = end

    state.set_draft(draft, clock=clock)
    if state.pending_confirmation is not None:
        state.clear_pending(clock=clock)

    if draft.is_complete():
        return await _stage_draft(state, service, actor, draft, clock=clock)


    label = draft.leave_type_name or "leave"
    parts: list[str] = []
    if draft.start_date is not None:
        parts.append(f"{label} would start on {format_short(draft.start_date)}.")
    ui_widget: dict[str, Any] | None = None
    if draft.leave_type_name is None:
        parts.append("Which leave type would you like to take?")
        try:
            types_result = await list_leave_types(service, actor)
            ui_widget = _leave_types_widget(types_result)
        except Exception:
            ui_widget = None
    elif draft.start_date is None:
        parts.append("From which date would you like to start?")
        ui_widget = _leave_date_picker_widget(draft, today=today)
    else:
        parts.append("To which date would you like to end?")
        ui_widget = _leave_date_picker_widget(draft, today=today)
    return _reply(state, " ".join(parts), clock=clock, ui_widget=ui_widget)


# ---- deterministic cancel / decision flow ----------------------------------
#
# Write actions on EXISTING requests are referenced by their human-readable
# LR-YYYY-XXX number, never an internal UUID — and the number is resolved by
# code, not by the model. When the employee's message names a reference the
# action is staged deterministically (preflighted against the real request);
# when it doesn't, the agent asks for the reference (listing what CAN be
# cancelled), instead of letting the model invent one.

_CANCEL_INTENT_WORDS = ("cancel", "withdraw")
_DECIDE_INTENT_WORDS = ("reject", "deny")
_REFERENCE_RE = re.compile(r"LR-\d{4}-\d{3,}", re.IGNORECASE)


def _extract_reference(text: str) -> str | None:
    """The LR-YYYY-XXX request reference in the message, uppercased, or None."""
    match = _REFERENCE_RE.search(text)
    return match.group(0).upper() if match else None


def _has_request_context(text: str) -> bool:
    """The message is about leave requests at all (not, say, cancelling a draft)."""
    return "leave" in text or "request" in text


async def _stage_reference_write(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    args: dict,
    *,
    clock: Clock,
) -> AgentTurnResult:
    """Preflight + stage a reference-based write action deterministically."""
    extra_details: dict[str, Any] = {}
    try:
        if tool_name == "cancel_leave_request":
            await preflight_cancel(service, actor, args["request_number"])
        else:
            req = await preflight_hr_reference(service, actor, args["request_number"])
            if req:
                emp_name = None
                emp_code = None
                try:
                    from app.domain.identity import Employee, Person
                    emp = await service._db.get(Employee, req.employee_id)
                    if emp:
                        emp_code = emp.employee_code
                        p = await service._db.get(Person, emp.person_id)
                        if p:
                            emp_name = f"{p.first_name} {p.last_name}".strip()
                except Exception:
                    pass
                extra_details = {
                    "employee_name": emp_name,
                    "employee_code": emp_code,
                    "start_date": req.start_date.isoformat(),
                    "end_date": req.end_date.isoformat(),
                    "total_days": str(req.total_days),
                    "reason": req.reason,
                }
    except ToolError as err:
        return _reply(state, str(err), clock=clock)

    summary = prompts.summarize_for_confirmation(tool_name, args)
    state.stage(tool_name, args, summary, clock=clock)
    staged_args = {**args, **extra_details}
    return _reply(
        state, summary, clock=clock,
        ui_widget=_staged_action_widget(tool_name, staged_args, summary),
    )


async def _intercept_employee_cancel(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer a cancel-intent turn deterministically (no model).

    With a reference: stage the cancel for confirmation. Without one: list
    the employee's pending requests and ask which one — the model is never
    asked to guess a request number.
    """
    lowered = user_message.lower()
    if not any(word in lowered for word in _CANCEL_INTENT_WORDS) or not _has_request_context(lowered):
        return None

    # The employee pivoted to cancelling an existing request: an in-progress
    # application draft and any stale staged action are no longer meant — a
    # later "yes" must not fire the old submit.
    state.clear_draft(clock=clock)
    state.clear_pending(clock=clock)

    reference = _extract_reference(user_message)
    if reference is not None:
        return await _stage_reference_write(
            state, service, actor, "cancel_leave_request",
            {"request_number": reference}, clock=clock,
        )

    try:
        lines = await pending_request_lines(service, actor)
    except ToolError as err:
        return _reply(state, str(err), clock=clock)
    if not lines:
        return _reply(
            state, "You have no pending leave requests to cancel.", clock=clock
        )
    return _reply(
        state,
        "Which request would you like to cancel? "
        + " — ".join(lines)
        + ".\nReply with the request number (e.g., LR-2026-001).",
        clock=clock,
    )


_HR_LIST_VIEW_WORDS = ("see", "show", "list", "view")
_HR_LIST_ALL_WORDS = ("all", "every")


def _is_hr_list_all_intent(user_message: str) -> bool:
    """Is this HR message asking to SEE the leave requests (all of them)?

    Conservative by design — only a clear request-list framing counts: a
    view word ("see", "show", "list", "view") or an "all"/"every"
    qualifier together with the word "request". Balance, type, pending,
    decide/cancel, and single-reference messages are excluded so the
    interception never hijacks a flow that belongs elsewhere.
    """
    lowered = user_message.lower()
    if not _has_request_context(lowered):
        return False
    if "balance" in lowered or "type" in lowered or "pending" in lowered:
        return False
    if _extract_reference(lowered) is not None:
        return False
    if any(word in lowered for word in _CANCEL_INTENT_WORDS) or any(
        word in lowered for word in _DECIDE_INTENT_WORDS
    ) or "approve" in lowered:
        return False
    if "request" not in lowered:
        return False
    return any(word in lowered for word in _HR_LIST_VIEW_WORDS) or any(
        word in lowered for word in _HR_LIST_ALL_WORDS
    )


async def _intercept_hr_reference_write(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer a manager's cancel/approve/reject/list intent deterministically.

    Same discipline as the employee path: the LR-YYYY-XXX reference is
    resolved by code, never inferred. With no reference the manager is
    shown what CAN be acted on — all pending requests across employees —
    and asked for the number, so the flow never dead-ends at "which
    request number?" with nothing to look at. ``approve`` is read from the
    intent words, never inferred by the model.
    """
    if actor.coarse_role != "HR_ADMIN":
        return None
    lowered = user_message.lower()
    if not _has_request_context(lowered):
        return None

    cancel = any(word in lowered for word in _CANCEL_INTENT_WORDS)
    approve = "approve" in lowered
    reject = any(word in lowered for word in _DECIDE_INTENT_WORDS)
    # Explicit "pending" asks and general "see all requests" asks are both
    # answered deterministically — a listing is never left to the model to
    # pick between the near-identical list_leave_requests and
    # list_my_leave_requests tools (an administrator who asks to see the
    # requests must see them, not hear that they have no leave of their own).
    listing = "pending" in lowered
    list_all = _is_hr_list_all_intent(lowered)
    if not approve and not reject and not listing and not list_all:
        if cancel:
            # Cancelling is the employee's own action — an administrator
            # cannot cancel requests, not even by reference.
            state.clear_draft(clock=clock)
            state.clear_pending(clock=clock)
            return _reply(
                state,
                "Cancelling a leave request is the employee's own action — as "
                "an administrator you can approve or reject requests, but not "
                "cancel them.",
                clock=clock,
            )
        return None

    # Same pivot semantics as the employee cancel path: acting on (or just
    # viewing) existing requests supersedes any in-progress application.
    state.clear_draft(clock=clock)
    state.clear_pending(clock=clock)

    reference = _extract_reference(user_message)
    if reference is None:
        if list_all:
            # "see all requests" is a read view: the manager tool's full
            # pipeline, pending and decided, formatted deterministically —
            # the model never gets a chance to route it to a self-service
            # tool and the role gate never fires its misleading refusal.
            try:
                result = await list_leave_requests(service, actor)
            except ToolError as err:
                return _reply(state, str(err), clock=clock)
            text = format_tool_result("list_leave_requests", result)
            return _reply(
                state, text, clock=clock,
                tool_called="list_leave_requests", tool_result=result,
                ui_widget=_leave_requests_widget(result, is_manager=True),
            )
        try:
            lines = await hr_pending_request_lines(service, actor)
        except ToolError as err:
            return _reply(state, str(err), clock=clock)
        if not lines:
            return _reply(
                state, "There are no pending leave requests to act on.", clock=clock
            )
        pending_result = []
        try:
            pending_result = [r for r in await list_leave_requests(service, actor) if r.get("status") == "PENDING"]
        except Exception:
            pass
        return _reply(
            state,
            "Here are the pending leave requests:\n"
            + "\n".join(f"- {line}" for line in lines)
            + "\n\nReply with the request number (e.g., LR-2026-001) to "
            "approve or reject one.",
            clock=clock,
            ui_widget=_leave_requests_widget(pending_result, is_manager=True) if pending_result else None,
        )

    tool_name, args = "decide_leave_request", {
        "request_number": reference,
        "approve": approve,
    }
    return await _stage_reference_write(state, service, actor, tool_name, args, clock=clock)


async def _intercept_reference_writes(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Route a cancel/decision turn to the right deterministic handler.

    Employees get the self-service cancel flow; HR administrators get the
    manager flow (which also covers their own requests, since the manager
    tools can act on any request).
    """
    if actor.coarse_role == "HR_ADMIN":
        return await _intercept_hr_reference_write(state, service, actor, user_message, clock=clock)
    return await _intercept_employee_cancel(state, service, actor, user_message, clock=clock)


async def _handle_stage(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    raw_args: dict,
    *,
    clock: Clock,
    raw_model_action: dict,
) -> AgentTurnResult:
    """Validate + stage a proposed write action.

    For `submit_leave_request` this runs a deterministic preflight against
    the employee's real balance BEFORE anything is staged or confirmed —
    so "not enough balance" is surfaced the moment the employee gives
    dates, never after a confirmation the service would reject anyway.
    """
    spec = TOOLS.get(tool_name)
    if spec is None or not spec.requires_confirmation:
        logger.warning("Leave Agent: model staged invalid tool %r", tool_name)
        return _reply(state, _FALLBACK_UNPARSEABLE, clock=clock, raw_model_action=raw_model_action)

    try:
        if tool_name == "submit_leave_request" and state.draft is not None and state.draft.is_complete():
            # The deterministic draft is authoritative over what the model
            # staged — it was built from resolved dates, never guesses.
            canonical = _draft_canonical(state.draft)
            state.clear_draft(clock=clock)
        else:
            canonical = canonical_args(tool_name, raw_args)
        if tool_name == "submit_leave_request":
            # Preflight needs real date objects (not ISO strings) and does
            # not take `reason` (the draft always carries one).
            preflight_args = validate_args(tool_name, canonical)
            working_days, holidays_in_range = await preflight_submit(
                service,
                actor,
                leave_type_name=preflight_args["leave_type_name"],
                start_date=preflight_args["start_date"],
                end_date=preflight_args["end_date"],
                is_half_day=preflight_args.get("is_half_day", False),
                half_day_period=preflight_args.get("half_day_period"),
            )
            summary = prompts.summarize_for_confirmation(
                tool_name,
                canonical,
                working_days=working_days,
                holidays=holidays_in_range,
            )
        elif tool_name == "cancel_leave_request":
            await preflight_cancel(service, actor, canonical["request_number"])
            summary = prompts.summarize_for_confirmation(tool_name, canonical)
        elif tool_name == "decide_leave_request":
            await preflight_hr_reference(service, actor, canonical["request_number"])
            summary = prompts.summarize_for_confirmation(tool_name, canonical)
        else:
            summary = prompts.summarize_for_confirmation(tool_name, canonical)
    except ToolError as err:
        return _reply(state, str(err), clock=clock, raw_model_action=raw_model_action)

    # Deterministic summary, not the model's own phrasing for this turn —
    # what the employee is asked to confirm must never depend solely on
    # the model getting the wording right.
    state.stage(tool_name, canonical, summary, clock=clock)
    return _reply(
        state, summary, clock=clock, raw_model_action=raw_model_action,
        ui_widget=_staged_action_widget(tool_name, canonical, summary),
    )


_HR_SELF_SERVICE_LIST_TOOLS = ("list_my_leave_requests", "list_leave_types")


async def _recover_hr_list_all(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    user_message: str,
    *,
    clock: Clock,
    raw_model_action: dict,
) -> AgentTurnResult | None:
    """Turn a self-service role-gate rejection into the manager list.

    The model can pick the near-identical list_my_leave_requests (or
    list_leave_types) for an administrator's request-listing ask; the
    self-service gate then rejects it with the "you have no leave of your
    own" refusal. When the message really is a listing ask (request
    context, no balance/type/pending/action/reference intent) the right
    answer is the manager tool's full list — execute it instead.
    """
    if actor.coarse_role != "HR_ADMIN":
        return None
    if tool_name not in _HR_SELF_SERVICE_LIST_TOOLS:
        return None
    lowered = user_message.lower()
    if not _has_request_context(lowered):
        return None
    if "balance" in lowered or "type" in lowered or "pending" in lowered:
        return None
    if any(word in lowered for word in _CANCEL_INTENT_WORDS) or any(
        word in lowered for word in _DECIDE_INTENT_WORDS
    ) or "approve" in lowered:
        return None
    if _extract_reference(lowered) is not None:
        return None
    try:
        result = await list_leave_requests(service, actor)
    except ToolError as err:
        return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)
    text = format_tool_result("list_leave_requests", result)
    return _reply(
        state, text, clock=clock,
        tool_called="list_leave_requests", tool_result=result,
        raw_model_action=raw_model_action,
        ui_widget=_leave_requests_widget(result, is_manager=True),
    )


async def _handle_read(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    raw_args: dict,
    *,
    clock: Clock,
    raw_model_action: dict,
    model_reply: str | None = None,
    user_message: str = "",
) -> AgentTurnResult:
    """Validate + execute a read tool. Reply is always the deterministic
    formatting of the actual result — never the model's pre-execution text."""
    spec = TOOLS[tool_name]
    try:
        args = validate_args(tool_name, raw_args)
        result = await spec.handler(service, actor, **args)
    except ToolError as err:
        # The model routed an administrator's "see all requests" ask to a
        # self-service list tool whose role gate refuses it — recover by
        # executing the manager tool instead of relaying the refusal.
        recovered = await _recover_hr_list_all(
            state, service, actor, tool_name, user_message,
            clock=clock, raw_model_action=raw_model_action,
        )
        if recovered is not None:
            return recovered
        return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)

    logger.info("Leave Agent: executed read tool %s (args=%r)", tool_name, args)

    ui_widget: dict[str, Any] | None = None
    if tool_name == "get_leave_balance":
        ui_widget = _leave_balance_widget(result, year=args.get("year"))
    elif tool_name == "get_employee_leave_balance":
        emp_name = result[0].get("employee_name") if result else None
        emp_code = result[0].get("employee_code") if result else args.get("employee_code")
        ui_widget = _leave_balance_widget(
            result,
            year=args.get("year"),
            employee_code=emp_code,
            employee_name=emp_name,
        )
    elif tool_name == "list_leave_types":
        ui_widget = _leave_types_widget(result)
    elif tool_name == "list_my_leave_requests":
        ui_widget = _leave_requests_widget(result, is_manager=False)
    elif tool_name == "list_leave_requests":
        ui_widget = _leave_requests_widget(result, is_manager=True)
    elif tool_name == "list_all_employee_balances":
        ui_widget = {"type": "all_employee_balances", "employees": result, "year": args.get("year", clock.today().year)}
    elif tool_name == "get_leave_request":
        ui_widget = {"type": "single_leave_request", "request": result}
    elif tool_name == "list_company_holidays":
        ui_widget = {"type": "company_holidays", "holidays": result}
    elif tool_name == "get_team_out_of_office":
        ui_widget = {"type": "team_out_of_office", "entries": result}

    if tool_name == "list_leave_types":
        override = _list_types_reply_override(user_message)
        if override is not None:
            # The model fell back to list_leave_types on a message that is
            # not a request start or a types question — the type dump would
            # answer a question nobody asked. Ask what action instead.
            return _reply(
                state,
                override,
                clock=clock,
                tool_called=tool_name,
                tool_result=result,
                raw_model_action=raw_model_action,
                ui_widget=ui_widget,
            )

    text = format_tool_result(tool_name, result)

    if tool_name == "list_leave_types" and _is_request_intent(user_message) and "type" not in user_message.lower():
        # "can i get leave?" / "i want to apply for leave" — a request start
        # without a named type. The model dumped the type list, but the list
        # answers a question nobody asked: drop it and let the deterministic
        # follow-up below ask "which type?" on its own.
        text = ""

    # When the balance came back usable (>0) and the employee asked to
    # START a request, always ask for the dates — this must not depend on
    # the model remembering to phrase a question. The model's own
    # follow-up is only used as second opinion when it's an actual
    # question; otherwise the deterministic one stands. A usable balance
    # also opens a deterministic draft, so the follow-up date answers are
    # resolved by code, not by the model. The same applies to a
    # list_leave_types reply for a request intent: the type list alone is
    # never the end of the turn — the draft opens and the next question is
    # asked deterministically, so "apply leave" can't dead-end at
    # "available leave types only".
    follow_up = _request_follow_up(tool_name, result, user_message) or _model_question(model_reply)
    if follow_up:
        text = f"{text}\n\n{follow_up}" if text else follow_up
        candidates = _candidate_types(tool_name, result)
        if state.draft is None and candidates:
            draft = DraftRequest(leave_type_name=candidates[0] if len(candidates) == 1 else None)
            state.set_draft(draft, clock=clock)
            if draft.leave_type_name is not None:
                ui_widget = _leave_date_picker_widget(draft, today=clock.today())
    return _reply(
        state, text, clock=clock, tool_called=tool_name, tool_result=result,
        raw_model_action=raw_model_action, ui_widget=ui_widget,
    )


_REQUEST_INTENT_WORDS = (
    "want",
    "would like",
    "request",
    "apply",
    "book",
    "take off",
    "need",
    "get",
    "take",
    "avail",
    "i'd like",
    "id like",
    "can i have",
    "go on leave",
    "going on leave",
)

# Manager-scope vocabulary. When an HR admin's message contains any of these
# it is about REVIEWING others' leave (list/approve flows), never about
# applying for their own — the self-service apply guard must stay silent.
_MANAGER_SCOPE_WORDS = (
    "all",
    "pending",
    "team",
    "everyone",
    "employees",
    "employee's",
    "employees'",
    "list",
    "show",
    "view",
    "see",
    "review",
    "requests",
    "what",
)


def _is_manager_scope_ask(lowered: str) -> bool:
    """Is this HR-admin message about managing others' leave, not applying?"""
    return any(word in lowered for word in _MANAGER_SCOPE_WORDS)


def _is_request_intent(user_message: str) -> bool:
    lowered = user_message.lower()
    # "avail" is a substring of "available" — "is annual leave available?"
    # is a question about availability, never a request start. Only an
    # unambiguous request verb keeps it a request intent. A balance ask
    # ("get me leave balance", "get my leave") is never a request start
    # either — it is answered from the balance, not by asking which type.
    available_only = "available" in lowered and not any(
        word in lowered for word in ("want", "would like", "apply", "request", "book")
    )
    return (
        any(word in lowered for word in _REQUEST_INTENT_WORDS)
        and not available_only
        and not _is_balance_ask(user_message)
    )


def _usable_leave_types(result: Any) -> list[str]:
    """The leave types in a balance result with remaining days > 0."""
    if not result:
        return []
    usable: list[str] = []
    for row in result:
        try:
            if Decimal(row["remaining_days"]) > 0:
                usable.append(row["leave_type_name"])
        except (KeyError, TypeError, ValueError):
            continue
    return usable


def _candidate_types(tool_name: str, result: Any) -> list[str]:
    """Leave type names a request could start with, from a read tool result.

    `get_leave_balance` contributes the types with actual remaining days;
    `list_leave_types` contributes everything that exists. Either way a
    single name pre-fills the draft, several leave the type open so the
    employee's next message names it and the deterministic interceptor
    resolves it.
    """
    if tool_name == "get_leave_balance":
        return _usable_leave_types(result)
    if tool_name == "list_leave_types":
        if not result:
            return []
        return [t["leave_name"] for t in result]
    return []


def _request_follow_up(tool_name: str, result: Any, user_message: str) -> str | None:
    """Deterministic next step after a balance/type check for a request intent."""
    lowered = user_message.lower()
    if tool_name == "get_leave_balance":
        usable = _usable_leave_types(result)
        if not usable:
            return None
        # "get"/"take"/"avail" etc. are request-intent words, but a balance
        # QUESTION is not a request start — never ask for dates after a
        # balance answer.
        if any(word in lowered for word in ("balance", "remaining", "left", "how much", "do i have", "available")):
            return None
        names = ", ".join(usable)
        return (
            f"You can request {names}. What dates would you like, "
            "and any reason for the leave?"
        )
    if tool_name == "list_leave_types":
        if not result:
            return None
        if "type" in lowered:
            # A direct question about types — the list itself is the answer.
            return None
        if _is_request_intent(user_message):
            return "Which leave type would you like to take?"
    return None


_LIST_TYPES_FALLBACK_REPLY = (
    "I can help you check your leave balance, apply for leave, view your "
    "requests, or cancel a pending request — what would you like to do?"
)


def _list_types_reply_override(user_message: str) -> str | None:
    """Override text when the model used list_leave_types as a general
    fallback for a message that is neither a request start nor a question
    about types.

    list_leave_types is the right tool only when the employee is clearly
    opening a request without naming a type (the deterministic draft flow
    then asks "which type?") or asking what types exist at all. Anything
    else — an ambiguous message the model didn't know how to route — must
    not be answered by dumping "Available leave types: ...": ask what
    action they want instead.
    """
    lowered = user_message.lower()
    if _is_request_intent(user_message):
        return None
    if "type" in lowered:
        return None
    return _LIST_TYPES_FALLBACK_REPLY


def _model_question(model_reply: str | None) -> str | None:
    """The model's own question, when it actually phrased one — anything
    ending in '?' that isn't just the deterministic text repeated."""
    if not model_reply:
        return None
    stripped = model_reply.strip()
    if not stripped.endswith("?"):
        return None
    return stripped


async def _handle_confirmed_write(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    raw_args: dict,
    *,
    clock: Clock,
    raw_model_action: dict,
) -> AgentTurnResult:
    """Execute a write tool — ONLY if it exactly matches a currently staged,
    unexpired confirmation. This is what actually enforces the confirmation
    gate: a real code condition, not something the prompt merely asks the
    model to respect (02-base-architecture.md §3.2 — the agent cannot be
    prompted into bypassing a server-side check).
    """
    try:
        args = canonical_args(tool_name, raw_args)
    except ToolError as err:
        return _reply(state, str(err), clock=clock, raw_model_action=raw_model_action)

    pending = state.pending_confirmation

    if pending is not None and pending.tool == tool_name and state.pending_is_expired(clock=clock):
        state.clear_pending(clock=clock)
        return _reply(state, _FALLBACK_EXPIRED, clock=clock, raw_model_action=raw_model_action)

    if pending is None or pending.tool != tool_name or pending.args != args:
        logger.warning(
            "Leave Agent: blocked call_tool for %r — no matching staged confirmation "
            "(pending=%r, requested_args=%r)",
            tool_name, pending, args,
        )
        state.clear_pending(clock=clock)
        return _reply(state, _FALLBACK_NO_MATCH, clock=clock, raw_model_action=raw_model_action)

    # Atomic claim: prevents two concurrent confirmations for this session
    # (a double-submitted "yes", or a retried request) from both executing.
    # Check-and-set with no `await` between them, so within this event loop
    # it's a true single decision point.
    if not state.begin_execution():
        return _reply(state, _FALLBACK_ALREADY_RUNNING, clock=clock, raw_model_action=raw_model_action)

    try:
        spec = TOOLS[tool_name]
        try:
            result = await spec.handler(service, actor, **validate_args(tool_name, raw_args))
        except ToolError as err:

            # Business-rule rejection (insufficient balance, not found, ...)
            # — relay plainly, never report success from the model's text.
            state.clear_pending(clock=clock)
            return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)

        state.clear_pending(clock=clock)
        text = format_tool_result(tool_name, result)
        ui_widget = _action_result_widget(tool_name, result)
        return _reply(
            state, text, clock=clock, tool_called=tool_name, tool_result=result,
            raw_model_action=raw_model_action, ui_widget=ui_widget,
        )
    finally:
        state.end_execution(clock=clock)


def _validate_response(raw: Any) -> tuple[str, str, str | None, dict] | None:
    """Validate the model's parsed JSON against the expected top-level shape.

    (Per-tool argument validation happens separately, in tools.py, via
    validate_args/canonical_args — this only checks the envelope: a valid
    action, a non-empty reply, and a known tool name where one is required.)
    """
    if not isinstance(raw, dict):
        return None
    action = raw.get("action")
    reply_text = raw.get("reply")
    tool_name = raw.get("tool")
    args = raw.get("args", {})

    if action not in _VALID_ACTIONS:
        return None
    if not isinstance(reply_text, str) or not reply_text.strip():
        return None
    if action in ("stage", "call_tool"):
        if not isinstance(tool_name, str) or tool_name not in TOOLS:
            return None
    if not isinstance(args, dict):
        return None

    return action, reply_text, tool_name, args
