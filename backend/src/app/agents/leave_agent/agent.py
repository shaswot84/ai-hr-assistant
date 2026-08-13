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

from app.agents.leave_agent import prompts
from app.agents.leave_agent.dates import extract_dates, format_short, resolve_end_date
from app.agents.leave_agent.state import DraftRequest, LeaveAgentState
from app.agents.leave_agent.tools import (
    TOOLS,
    ToolError,
    canonical_args,
    format_tool_result,
    hr_pending_request_lines,
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

    intercepted = _intercept_draft_turn(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    intercepted = _intercept_reference_writes(state, service, actor, user_message, clock=clock)
    if intercepted is not None:
        state.add_turn("employee", user_message, clock=clock)
        return intercepted

    system_prompt = prompts.build_system_prompt()
    turn_prompt = prompts.build_turn_prompt(
        user_message,
        history=state.history_for_prompt(),
        pending_confirmation=state.pending_for_prompt(),
        draft=state.draft_for_prompt(),
    )

    try:
        raw = await chat_provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=turn_prompt,
            temperature=0.2,  # low — this is a routing/extraction task, not creative writing
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
) -> AgentTurnResult:
    """Record the agent's turn and build the result — the one place this
    "append history, then return" pairing happens, instead of repeated
    inline at every call site."""
    state.add_turn("agent", text, clock=clock)
    return AgentTurnResult(reply=text, tool_called=tool_called, tool_result=tool_result, raw_model_action=raw_model_action)


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
)


def _draft_canonical(draft: DraftRequest) -> dict:
    """Draft -> the JSON-safe canonical args shape of submit_leave_request,
    matching tools.canonical_args (mode="json") so the staged-vs-confirmed
    equality check in _handle_confirmed_write works unchanged."""
    return {
        "leave_type_name": draft.leave_type_name,
        "start_date": draft.start_date.isoformat(),
        "end_date": draft.end_date.isoformat(),
        "reason": draft.reason,
    }


def _stage_draft(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    draft: DraftRequest,
    *,
    clock: Clock,
) -> AgentTurnResult:
    """Preflight + stage a completed draft deterministically.

    Preflight runs against the employee's REAL balance and existing
    requests before anything is staged — a draft that can't succeed is
    surfaced as a plain-language reply, and the draft is kept so the
    employee can adjust the dates.
    """
    canonical = _draft_canonical(draft)
    try:
        preflight_args = validate_args("submit_leave_request", canonical)
        preflight_submit(
            service,
            actor,
            leave_type_name=preflight_args["leave_type_name"],
            start_date=preflight_args["start_date"],
            end_date=preflight_args["end_date"],
        )
    except ToolError as err:
        return _reply(state, str(err), clock=clock)

    summary = prompts.summarize_for_confirmation("submit_leave_request", canonical)
    state.stage("submit_leave_request", canonical, summary, clock=clock)
    state.clear_draft(clock=clock)
    return _reply(state, summary, clock=clock)


def _intercept_draft_turn(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    user_message: str,
    *,
    clock: Clock,
) -> AgentTurnResult | None:
    """Answer a date-bearing or draft-continuing turn WITHOUT the model.

    Returns None when there is nothing deterministic to say — the normal
    model flow takes over. Never guesses: unresolved dates are asked for
    again in plain language.
    """
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
        # Cancel/decision turns belong to the reference-write interception
        # below, never to the draft flow: a relative date in such a message
        # ("cancel the one from last monday") must not read as "start the
        # application", and the pivot clears any in-progress draft there.
        return None

    today = clock.today()
    start, end = extract_dates(user_message, today)

    draft = state.draft
    if draft is None:
        if not _is_request_intent(user_message) or start is None:
            return None
        draft = DraftRequest()

    if actor.coarse_role == "HR_ADMIN":
        # HR has no leave of their own: a date-bearing application (or a
        # continuation of a leftover draft) from an administrator is a role
        # mismatch, not something to draft — refuse deterministically, the
        # model is never asked to explain a request the manager can't make.
        return _reply(
            state,
            "As an HR administrator you can review employees' leave requests "
            "and approve, reject, or cancel them — but you can't apply for "
            "leave yourself.",
            clock=clock,
        )

    if start is None and end is None and state.draft is not None and state.draft.start_date is not None:
        # An end-only follow-up ("for 3 days", "to friday") resolves against
        # the draft's already-known start date, never against the model.
        end = resolve_end_date(user_message, state.draft.start_date, today)

    had_type = draft.leave_type_name is not None
    if draft.leave_type_name is None:
        mentioned = mentioned_leave_type(service, user_message)
        if mentioned is not None:
            draft.leave_type_name = mentioned

    progress = start is not None or end is not None
    if not had_type and draft.leave_type_name is not None:
        # The employee just named the type for a draft that had none — that
        # alone is progress, even without dates. (The pre-mutation value is
        # what matters: `draft` IS `state.draft`, so comparing the two after
        # mutation can never detect a change.)
        progress = True
    if not progress:
        return None

    if start is not None:
        draft.start_date = start
    if end is not None:
        draft.end_date = end

    state.set_draft(draft, clock=clock)
    if state.pending_confirmation is not None:
        # The employee changed their plans mid-confirmation; the old staged
        # action is stale and must not be confirmable anymore.
        state.clear_pending(clock=clock)

    if draft.is_complete():
        return _stage_draft(state, service, actor, draft, clock=clock)

    label = draft.leave_type_name or "leave"
    parts: list[str] = []
    if draft.start_date is not None:
        parts.append(f"{label} would start on {format_short(draft.start_date)}.")
    if draft.leave_type_name is None:
        parts.append("Which leave type would you like to take?")
    elif draft.start_date is None:
        parts.append("From which date would you like to start?")
    else:
        parts.append("To which date would you like to end?")
    return _reply(state, " ".join(parts), clock=clock)


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


def _stage_reference_write(
    state: LeaveAgentState,
    service: LeaveService,
    actor: UserContext,
    tool_name: str,
    args: dict,
    *,
    clock: Clock,
) -> AgentTurnResult:
    """Preflight + stage a reference-based write action deterministically."""
    try:
        if tool_name == "cancel_leave_request":
            preflight_cancel(service, actor, args["request_number"])
        else:
            preflight_hr_reference(service, actor, args["request_number"])
    except ToolError as err:
        return _reply(state, str(err), clock=clock)

    summary = prompts.summarize_for_confirmation(tool_name, args)
    state.stage(tool_name, args, summary, clock=clock)
    return _reply(state, summary, clock=clock)


def _intercept_employee_cancel(
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
        return _stage_reference_write(
            state, service, actor, "cancel_leave_request",
            {"request_number": reference}, clock=clock,
        )

    try:
        lines = pending_request_lines(service, actor)
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


def _intercept_hr_reference_write(
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
    # An explicit "pending" ask is answered deterministically; a general
    # "show me all requests" goes to the model's list_leave_requests tool,
    # which also shows decided ones.
    listing = "pending" in lowered
    if not approve and not reject and not listing:
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
        try:
            lines = hr_pending_request_lines(service, actor)
        except ToolError as err:
            return _reply(state, str(err), clock=clock)
        if not lines:
            return _reply(
                state, "There are no pending leave requests to act on.", clock=clock
            )
        return _reply(
            state,
            "Here are the pending leave requests:\n"
            + "\n".join(f"- {line}" for line in lines)
            + "\n\nReply with the request number (e.g., LR-2026-001) to "
            "approve or reject one.",
            clock=clock,
        )

    tool_name, args = "decide_leave_request", {
        "request_number": reference,
        "approve": approve,
    }
    return _stage_reference_write(state, service, actor, tool_name, args, clock=clock)


def _intercept_reference_writes(
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
        return _intercept_hr_reference_write(state, service, actor, user_message, clock=clock)
    return _intercept_employee_cancel(state, service, actor, user_message, clock=clock)


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
            preflight_submit(
                service,
                actor,
                leave_type_name=preflight_args["leave_type_name"],
                start_date=preflight_args["start_date"],
                end_date=preflight_args["end_date"],
            )
        elif tool_name == "cancel_leave_request":
            preflight_cancel(service, actor, canonical["request_number"])
        elif tool_name == "decide_leave_request":
            preflight_hr_reference(service, actor, canonical["request_number"])
    except ToolError as err:
        return _reply(state, str(err), clock=clock, raw_model_action=raw_model_action)

    # Deterministic summary, not the model's own phrasing for this turn —
    # what the employee is asked to confirm must never depend solely on
    # the model getting the wording right.
    summary = prompts.summarize_for_confirmation(tool_name, canonical)
    state.stage(tool_name, canonical, summary, clock=clock)
    return _reply(state, summary, clock=clock, raw_model_action=raw_model_action)


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
        result = spec.handler(service, actor, **args)
    except ToolError as err:
        return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)

    logger.info("Leave Agent: executed read tool %s (args=%r)", tool_name, args)
    text = format_tool_result(tool_name, result)

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
        text = f"{text}\n\n{follow_up}"
        candidates = _candidate_types(tool_name, result)
        if state.draft is None and candidates:
            state.set_draft(
                DraftRequest(leave_type_name=candidates[0] if len(candidates) == 1 else None),
                clock=clock,
            )
    return _reply(state, text, clock=clock, tool_called=tool_name, tool_result=result, raw_model_action=raw_model_action)


_REQUEST_INTENT_WORDS = ("want", "would like", "request", "apply", "book", "take off", "need")


def _is_request_intent(user_message: str) -> bool:
    lowered = user_message.lower()
    return any(word in lowered for word in _REQUEST_INTENT_WORDS)


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
    if not _is_request_intent(user_message):
        return None
    if tool_name == "get_leave_balance":
        usable = _usable_leave_types(result)
        if not usable:
            return None
        names = ", ".join(usable)
        return (
            f"You can request {names}. What dates would you like, "
            "and any reason for the leave?"
        )
    if tool_name == "list_leave_types":
        if not result:
            return None
        return "Which leave type would you like to take?"
    return None


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
            result = spec.handler(service, actor, **validate_args(tool_name, raw_args))
        except ToolError as err:
            # Business-rule rejection (insufficient balance, not found, ...)
            # — relay plainly, never report success from the model's text.
            state.clear_pending(clock=clock)
            return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)

        state.clear_pending(clock=clock)
        text = format_tool_result(tool_name, result)
        return _reply(state, text, clock=clock, tool_called=tool_name, tool_result=result, raw_model_action=raw_model_action)
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