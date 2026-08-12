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
from typing import Any

from app.agents.leave_agent import prompts
from app.agents.leave_agent.state import LeaveAgentState
from app.agents.leave_agent.tools import TOOLS, ToolError, canonical_args, format_tool_result, preflight_submit, validate_args
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
    """
    clock = clock or get_clock()

    system_prompt = prompts.build_system_prompt()
    turn_prompt = prompts.build_turn_prompt(
        user_message,
        history=state.history_for_prompt(),
        pending_confirmation=state.pending_for_prompt(),
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

    return await _handle_read(state, service, actor, tool_name, raw_args, clock=clock, raw_model_action=raw)


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
        canonical = canonical_args(tool_name, raw_args)
        if tool_name == "submit_leave_request":
            preflight_submit(service, actor, **canonical)
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
) -> AgentTurnResult:
    """Validate + execute a read tool. Reply is always the deterministic
    formatting of the actual result — never the model's pre-execution text."""
    spec = TOOLS[tool_name]
    try:
        args = validate_args(tool_name, raw_args)
        result = spec.handler(service, actor, **args)
    except ToolError as err:
        return _reply(state, str(err), clock=clock, tool_called=tool_name, raw_model_action=raw_model_action)

    text = format_tool_result(tool_name, result)
    return _reply(state, text, clock=clock, tool_called=tool_name, tool_result=result, raw_model_action=raw_model_action)


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