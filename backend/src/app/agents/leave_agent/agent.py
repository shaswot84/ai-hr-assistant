"""Leave Agent dispatch loop.

Single-shot pattern (Option A from the earlier design discussion): no
LangGraph, no native tool-calling API -- this mirrors exactly what
evaluation/scoring.py already proves out in production against the same
Ollama provider: one system prompt (rules + tool catalog + response
schema, built by prompts.py), one user prompt for this turn, one
complete_json() call, then this module deterministically decides what the
JSON response is allowed to do.

The model NEVER executes a write tool directly. Every "call_tool" for a
write tool is re-validated against a `pending_confirmation` that agent.py
itself set on a *previous* turn, using the *previously staged* args, not
whatever the model returns this time. This is deliberate defense in depth,
not redundancy for its own sake: it means a hallucinated or
prompt-injected "call_tool" on a write action, on a turn where nothing was
actually staged, can never fire -- it gets downgraded to a stage-and-ask
instead of a silent unauthorized action, matching the codebase's existing
"agent proposes, service/deterministic code decides" line (A2 Sec.3).

Callers own persistence. `handle_turn` is pure request/response -- it does
not read or write conversation history or `pending_confirmation` from any
store. The caller (today: whatever calls this directly in a route or
test; eventually: api/routes/leave_chat.py backed by a durable session
store) is responsible for loading `history`/`pending_confirmation` before
the call and persisting the returned ones after. See the earlier
discussion of the conversation-persistence gap -- this module doesn't
solve that, it just doesn't make it worse by inventing its own cache.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from app.agents.leave_agent.prompts import build_system_prompt, build_turn_prompt, summarize_for_confirmation
from app.agents.leave_agent.tools import TOOLS, ToolError
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.model_gateway.ollama import OllamaChatProvider
from app.model_gateway.provider import ChatProviderError

logger = logging.getLogger(__name__)

_ALLOWED_ROLES = ("EMPLOYEE", "HR_ADMIN")
_TEMPERATURE = 0.2  # low -- this is a tool-routing decision, not open-ended writing
_VALID_ACTIONS = {"reply", "stage", "call_tool"}
# Arg keys that must be coerced from the JSON string the model returns into
# a real `date` before a handler (typed `date` in its signature) is called.
_DATE_ARG_KEYS = {"start_date", "end_date"}


@dataclass
class TurnResult:
    """What one turn of the Leave Agent produced -- the caller persists
    `pending_confirmation` and appends `reply` to its own history/store."""

    reply: str
    pending_confirmation: dict | None
    tool_called: str | None = None
    tool_result: dict | list | None = None
    raw_model_action: str | None = field(default=None, repr=False)


def _reject_role(actor: UserContext) -> TurnResult:
    """Fail fast, before spending a token, for a role this agent never serves."""
    return TurnResult(
        reply="This assistant only handles an employee's own leave requests.",
        pending_confirmation=None,
    )


def _coerce_args(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    """Convert JSON-shaped args (all strings) into the types each handler expects.

    Only dates need this today -- `leave_request_id` stays a string (the
    handlers themselves do `uuid.UUID(...)`), and every other field is
    already the right shape coming out of JSON.
    """
    coerced = dict(args)
    for key in _DATE_ARG_KEYS:
        value = coerced.get(key)
        if isinstance(value, str):
            try:
                coerced[key] = date.fromisoformat(value)
            except ValueError as exc:
                raise ToolError(
                    f"\"{value}\" isn't a valid date for {tool_name}.{key} "
                    "(expected YYYY-MM-DD)."
                ) from exc
    return coerced


def _validate_required_params(tool_name: str, args: dict[str, Any]) -> None:
    """Check every `required: True` parameter in the tool's spec is present.

    Defensive only -- the handler's own signature will still raise a clear
    error for anything this misses. This just turns the common case (model
    forgot a required field) into a clean ToolError instead of a TypeError
    surfacing from deep inside the handler.
    """
    spec = TOOLS[tool_name]
    missing = [
        name
        for name, schema in spec.parameters.items()
        if schema.get("required") and name not in args
    ]
    if missing:
        raise ToolError(f"{tool_name} is missing required field(s): {', '.join(missing)}.")


def _run_tool(service: LeaveService, actor: UserContext, tool_name: str, args: dict[str, Any]) -> Any:
    """Validate params, coerce types, and invoke a tool's handler. Raises ToolError on any failure."""
    if tool_name not in TOOLS:
        raise ToolError(f"Unknown tool: {tool_name}.")
    _validate_required_params(tool_name, args)
    coerced = _coerce_args(tool_name, args)
    spec = TOOLS[tool_name]
    return spec.handler(service, actor, **coerced)


def _parse_model_response(data: dict[str, Any]) -> tuple[str, str | None, dict[str, Any], str]:
    """Defensively normalize the model's JSON into (action, tool, args, reply).

    Mirrors evaluation/scoring.py's `_normalize_review`-style coercion: never
    trust the model's shape, always fall back to something safe. An
    unrecognized `action` degrades to "reply" (never silently becomes
    "call_tool") so a malformed response can never accidentally execute
    anything.
    """
    reply = data.get("reply")
    reply = reply if isinstance(reply, str) and reply.strip() else "Sorry, could you rephrase that?"

    action = data.get("action")
    if action not in _VALID_ACTIONS:
        action = "reply"

    tool = data.get("tool")
    tool = tool if isinstance(tool, str) and tool in TOOLS else None

    args = data.get("args")
    args = args if isinstance(args, dict) else {}

    if action in ("stage", "call_tool") and tool is None:
        action = "reply"  # can't stage/call without a real tool name

    return action, tool, args, reply


async def handle_turn(
    db: Session,
    actor: UserContext,
    *,
    message: str,
    history: list[dict[str, str]] | None = None,
    pending_confirmation: dict | None = None,
) -> TurnResult:
    """Process one turn of conversation with the Leave Agent.

    `history`/`pending_confirmation` are supplied by the caller (loaded from
    wherever conversation state lives) and returned, updated, for the
    caller to persist -- this function holds no state of its own.
    """
    if actor.coarse_role not in _ALLOWED_ROLES:
        return _reject_role(actor)

    service = LeaveService(db)
    provider = OllamaChatProvider()

    if not provider.is_configured():
        # No deterministic fallback makes sense for open-ended conversation
        # the way evaluation/scoring.py's keyword scorer does for resumes --
        # degrade honestly instead of guessing at intent with regex.
        return TurnResult(
            reply="The leave assistant isn't available right now -- you can still use the "
            "Leave page directly to check your balance or submit a request.",
            pending_confirmation=pending_confirmation,
        )

    system_prompt = build_system_prompt()
    user_prompt = build_turn_prompt(message, history=history, pending_confirmation=pending_confirmation)

    try:
        data = await provider.complete_json(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=_TEMPERATURE,
        )
    except ChatProviderError:
        logger.warning("Leave Agent: chat provider call failed", exc_info=True)
        return TurnResult(
            reply="Something went wrong reaching the assistant -- please try again in a moment.",
            pending_confirmation=pending_confirmation,
        )

    action, tool, args, reply = _parse_model_response(data)

    # ---- "reply": conversational turn, no tool involved --------------
    if action == "reply":
        return TurnResult(reply=reply, pending_confirmation=None)

    spec = TOOLS[tool]

    # ---- "stage": propose a write action, do not execute it ----------
    if action == "stage":
        if not spec.requires_confirmation:
            # A read tool never needs staging -- treat this as the model
            # being confused and just run it directly instead of blocking
            # a harmless read behind a pointless confirmation step.
            action = "call_tool"
        else:
            try:
                _validate_required_params(tool, args)
                coerced = _coerce_args(tool, args)
            except ToolError as exc:
                return TurnResult(reply=str(exc), pending_confirmation=None)
            try:
                summary = summarize_for_confirmation(tool, args)
            except (KeyError, TypeError):
                summary = reply  # fall back to the model's own phrasing
            return TurnResult(
                reply=summary,
                pending_confirmation={"tool": tool, "args": coerced_to_jsonable(coerced)},
            )

    # ---- "call_tool" -----------------------------------------------------
    if spec.requires_confirmation:
        # Defense in depth (see module docstring): only actually execute a
        # write tool if THIS turn's pending_confirmation says so, and use
        # the args that were staged, not whatever the model just returned.
        if not pending_confirmation or pending_confirmation.get("tool") != tool:
            try:
                _validate_required_params(tool, args)
                coerced = _coerce_args(tool, args)
            except ToolError as exc:
                return TurnResult(reply=str(exc), pending_confirmation=None)
            try:
                summary = summarize_for_confirmation(tool, args)
            except (KeyError, TypeError):
                summary = reply
            return TurnResult(
                reply=summary,
                pending_confirmation={"tool": tool, "args": coerced_to_jsonable(coerced)},
            )
        args = pending_confirmation["args"]

    try:
        result = _run_tool(service, actor, tool, args)
    except ToolError as exc:
        return TurnResult(reply=str(exc), pending_confirmation=None, tool_called=tool)
    except Exception:  # noqa: BLE001 - never leak an internal error to the employee
        logger.exception("Leave Agent: unexpected error running tool %s", tool)
        return TurnResult(
            reply="Something went wrong completing that -- please try again.",
            pending_confirmation=None,
            tool_called=tool,
        )

    return TurnResult(
        reply=reply,
        pending_confirmation=None,
        tool_called=tool,
        tool_result=result,
    )


def coerced_to_jsonable(args: dict[str, Any]) -> dict[str, Any]:
    """Convert coerced Python types (date) back to JSON-safe strings before
    stashing `args` in `pending_confirmation`, which round-trips through the
    caller's session store and back into prompts.build_turn_prompt's
    `json.dumps(...)` call next turn."""
    return {k: (v.isoformat() if isinstance(v, date) else v) for k, v in args.items()}