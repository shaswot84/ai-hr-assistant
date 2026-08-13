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
    mentioned_leave_type,
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

    today = clock.today()
    start, end = extract_dates(user_message, today)

    draft = state.draft
    if draft is None:
        if not _is_request_intent(user_message) or start is None:
            return None
        draft = DraftRequest()

    if start is None and end is None and state.draft is not None and state.draft.start_date is not None:
        # An end-only follow-up ("for 3 days", "to friday") resolves against
        # the draft's already-known start date, never against the model.
        end = resolve_end_date(user_message, state.draft.start_date, today)

    if draft.leave_type_name is None:
        mentioned = mentioned_leave_type(service, user_message)
        if mentioned is not None:
            draft.leave_type_name = mentioned

    progress = start is not None or end is not None
    if draft.leave_type_name is not None and state.draft is not None and draft.leave_type_name != state.draft.leave_type_name:
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
    # resolved by code, not by the model.
    follow_up = _request_follow_up(tool_name, result, user_message) or _model_question(model_reply)
    if follow_up:
        text = f"{text}\n\n{follow_up}"
        usable = _usable_leave_types(result)
        if state.draft is None and usable:
            state.set_draft(
                DraftRequest(leave_type_name=usable[0] if len(usable) == 1 else None),
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


def _request_follow_up(tool_name: str, result: Any, user_message: str) -> str | None:
    """Deterministic next step after a balance check for a request intent."""
    if tool_name != "get_leave_balance":
        return None
    if not _is_request_intent(user_message):
        return None
    usable = _usable_leave_types(result)
    if not usable:
        return None
    names = ", ".join(usable)
    return (
        f"You can request {names}. What dates would you like, "
        "and any reason for the leave?"
    )


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