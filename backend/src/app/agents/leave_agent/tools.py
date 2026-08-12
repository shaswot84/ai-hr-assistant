"""Leave Agent tools: thin, employee-scoped wrappers around LeaveService.

Every tool here is a self-service action — balance, submit, list, get,
cancel. Deciding someone else's request (`decide_request` on LeaveService)
is deliberately not exposed here: that's a manager/HR_ADMIN review action,
out of scope for this employee-facing agent per 04-leave-agent.md §2,
regardless of the caller's role.

Scope note (HR_ADMIN): no tool below accepts an employee_id argument at
all — every LeaveService call resolves "own employee" from `actor` via
IdentityService. An HR_ADMIN using this agent can only ever act on their
own leave, the same as any EMPLOYEE. This isn't a role check that could
be misconfigured; it's structural (the parameter doesn't exist), and the
extra="forbid" Pydantic schemas below mean a model that hallucinates an
employee_id argument gets a validation error, not a silent bypass.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, ValidationError

from app.capabilities.leave import LeaveService, PermissionError_
from app.contracts.auth import UserContext
from app.domain.leave import LeaveRequest, LeaveType
from app.services.identity import IdentityError

_ALLOWED_ROLES = ("EMPLOYEE", "HR_ADMIN")


class ToolError(Exception):
    """A tool-level failure meant to be relayed to the user in plain language.

    Every failure mode a tool can hit — role gate, argument validation,
    identity resolution, permission, business-rule rejection — funnels
    into this one exception type before it ever reaches agent.py. That's
    deliberate: agent.py should never need to know the difference between
    "the args were malformed" and "the service rejected it for balance
    reasons" — it just relays str(err) plainly, per
    05-recruitment-agent.md §7, and never leaks an internal exception
    type or traceback to the employee.
    """


def _require_employee_access(actor: UserContext) -> None:
    """Defensive role gate, independent of whatever route called this tool."""
    if actor.coarse_role not in _ALLOWED_ROLES:
        raise ToolError(
            "Leave requests are only available to employees. "
            "This account isn't linked to an employee record."
        )


def _call_service(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a LeaveService method with uniform exception translation.

    Every tool's service call goes through this, so IdentityError,
    PermissionError_, and ValueError are ALWAYS converted to ToolError —
    not just on the tools someone remembered to guard. No internal
    exception type or message detail beyond str(err) crosses this
    boundary.
    """
    try:
        return fn(*args, **kwargs)
    except (IdentityError, PermissionError_, ValueError) as err:
        raise ToolError(str(err)) from err


# ---- per-tool argument schemas ---------------------------------------------
#
# extra="forbid" rejects any field the model invents that isn't part of the
# real contract (an employee_id override, a stray "force": true, etc.) —
# strict-schema validation, not just type coercion. Pydantic also does the
# type coercion agent.py used to skip entirely: "start_date": "2026-09-01"
# (a JSON string, which is all the model can ever produce) becomes a real
# `date` object here, before it ever reaches LeaveService.


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetLeaveBalanceArgs(_StrictArgs):
    year: int | None = None


class ListLeaveTypesArgs(_StrictArgs):
    pass


class ListMyLeaveRequestsArgs(_StrictArgs):
    pass


class GetLeaveRequestArgs(_StrictArgs):
    leave_request_id: uuid.UUID


class SubmitLeaveRequestArgs(_StrictArgs):
    leave_type_name: str
    start_date: date
    end_date: date
    reason: str | None = None


class CancelLeaveRequestArgs(_StrictArgs):
    leave_request_id: uuid.UUID


_ARGS_MODELS: dict[str, type[_StrictArgs]] = {
    "get_leave_balance": GetLeaveBalanceArgs,
    "list_leave_types": ListLeaveTypesArgs,
    "list_my_leave_requests": ListMyLeaveRequestsArgs,
    "get_leave_request": GetLeaveRequestArgs,
    "submit_leave_request": SubmitLeaveRequestArgs,
    "cancel_leave_request": CancelLeaveRequestArgs,
}


def _validate(tool_name: str, raw_args: dict[str, Any]) -> _StrictArgs:
    model_cls = _ARGS_MODELS.get(tool_name)
    if model_cls is None:
        raise ToolError(f"Unknown tool: {tool_name}")
    try:
        return model_cls.model_validate(raw_args)
    except ValidationError as err:
        problems = "; ".join(
            f"{'.'.join(str(loc) for loc in e['loc']) or tool_name}: {e['msg']}" for e in err.errors()
        )
        raise ToolError(f"That request wasn't valid ({problems}).") from err


def validate_args(tool_name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Validate + coerce a tool's raw (JSON-shaped) args against its schema.

    Returns a plain dict of real Python values (date objects, UUID
    objects, ...) ready to pass as **kwargs to the tool handler. Raises
    ToolError — never a raw pydantic.ValidationError — on any mismatch:
    wrong type, missing required field, unknown field, unparseable date,
    malformed UUID.
    """
    return _validate(tool_name, raw_args).model_dump(mode="python")


def canonical_args(tool_name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    """Validated args in a JSON-safe, canonical shape — used for the staged
    vs. confirmed args equality check in agent.py, so two semantically
    identical but differently-formatted JSON payloads (e.g. trailing
    whitespace, dict key order) compare equal instead of spuriously
    mismatching."""
    return _validate(tool_name, raw_args).model_dump(mode="json")


# ---- leave-type name resolution --------------------------------------------

# A small, conservative set of common HR synonyms. This is a hint only: an
# alias is used to find an EXACT (case-insensitive) match among the
# organization's actual active leave types, never to select a type on its
# own. If the aliased term doesn't exactly match a real leave type's name,
# it's discarded and resolution falls through to token matching below —
# an alias can never invent a match that wouldn't otherwise exist.
_LEAVE_TYPE_ALIASES: dict[str, str] = {
    "pto": "annual leave",
    "vacation": "annual leave",
    "holiday": "annual leave",
    "sick day": "sick leave",
    "sick days": "sick leave",
}


def _resolve_leave_type(service: LeaveService, leave_type_name: str) -> LeaveType:
    """Resolve a spoken leave-type name to a LeaveType row.

    Order: exact match -> alias-guided exact match -> unique word-token
    match -> fail closed with the available list. Deliberately NOT raw
    substring matching (`needle in haystack`) — that would let a short
    query like "an" match inside "Annual Leave" by character containment
    alone. Token matching instead splits both sides into whole words and
    only matches if the query's words are a subset of the type's words,
    so "sick" matches "Sick Leave" but a stray short fragment can't
    silently match something unrelated.
    """
    types = service.list_leave_types()
    if not types:
        raise ToolError("There are no active leave types configured.")

    needle = leave_type_name.strip().lower()

    exact = [t for t in types if t.leave_name.lower() == needle]
    if len(exact) == 1:
        return exact[0]

    aliased_term = _LEAVE_TYPE_ALIASES.get(needle)
    if aliased_term:
        alias_exact = [t for t in types if t.leave_name.lower() == aliased_term]
        if len(alias_exact) == 1:
            return alias_exact[0]

    needle_tokens = set(needle.split())
    token_matches = [t for t in types if needle_tokens and needle_tokens <= set(t.leave_name.lower().split())]
    if len(token_matches) == 1:
        return token_matches[0]

    available = ", ".join(t.leave_name for t in types)
    if token_matches:  # more than one — genuinely ambiguous, fail closed
        raise ToolError(
            f"'{leave_type_name}' matches more than one leave type "
            f"({', '.join(t.leave_name for t in token_matches)}). Which one did you mean?"
        )
    raise ToolError(
        f"I don't see a leave type called '{leave_type_name}'. Available types: {available}."
    )


# ---- result serialization / deterministic formatting -----------------------


def _serialize_request(request: LeaveRequest, leave_type_name: str) -> dict[str, Any]:
    """Convert a LeaveRequest into a JSON-safe dict."""
    return {
        "leave_request_id": str(request.leave_request_id),
        "request_number": request.request_number,
        "leave_type_name": leave_type_name,
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "total_days": str(request.total_days),
        "reason": request.reason,
        "status": request.status,
        "submitted_at": request.submitted_at.isoformat(),
        "decided_at": request.decided_at.isoformat() if request.decided_at else None,
    }


def _leave_type_name(service: LeaveService, leave_type_id: uuid.UUID) -> str:
    leave_type = service._leave_types.get(leave_type_id)
    return leave_type.leave_name if leave_type else "Unknown"


def preflight_submit(
    service: LeaveService,
    actor: UserContext,
    *,
    leave_type_name: str,
    start_date: date,
    end_date: date,
) -> None:
    """Fail fast BEFORE a submission is staged/confirmed.

    Called at stage time (agent.py `_handle_stage`) with the employee's
    real balance from `service.list_my_balance` — never from the model's
    words. Raises ToolError with the exact reason the request can't
    succeed (insufficient balance, unknown type, broken date range), so
    the employee learns "you have 0.0 days of Unpaid Leave" the moment
    they give dates, instead of after confirming.
    """
    _require_employee_access(actor)
    if end_date < start_date:
        raise ToolError("End date must be on or after the start date.")
    leave_type = _resolve_leave_type(service, leave_type_name)
    if leave_type.max_consecutive_days and (end_date - start_date).days + 1 > leave_type.max_consecutive_days:
        raise ToolError(
            f"{leave_type.leave_name} cannot be taken for more than "
            f"{leave_type.max_consecutive_days} consecutive day(s)."
        )

    rows = _call_service(service.list_my_balance, actor, start_date.year)
    row = next((r for r in rows if r["leave_type"].leave_type_id == leave_type.leave_type_id), None)
    if row is None:
        raise ToolError(
            f"You don't have a {leave_type.leave_name} balance for {start_date.year}."
        )
    remaining = row["remaining_days"]
    total_days = Decimal((end_date - start_date).days + 1)
    if total_days > remaining:
        raise ToolError(
            f"Not enough {leave_type.leave_name} balance: "
            f"{remaining} day(s) remaining, {total_days} requested."
        )


# ---- read tools (no confirmation) -----------------------------------------


def get_leave_balance(service: LeaveService, actor: UserContext, *, year: int | None = None) -> list[dict]:
    """Return the employee's allocated/used/remaining days per leave type."""
    _require_employee_access(actor)
    rows = _call_service(service.list_my_balance, actor, year)
    return [
        {
            "leave_type_name": row["leave_type"].leave_name,
            "year": row["year"],
            "allocated_days": str(row["allocated_days"]),
            "used_days": str(row["used_days"]),
            "remaining_days": str(row["remaining_days"]),
        }
        for row in rows
    ]


def list_leave_types(service: LeaveService, actor: UserContext) -> list[dict]:
    """List active leave types the employee can request."""
    _require_employee_access(actor)
    types = _call_service(service.list_leave_types)
    return [
        {
            "leave_name": t.leave_name,
            "description": t.description,
            "is_paid": t.is_paid,
            "max_consecutive_days": t.max_consecutive_days,
        }
        for t in types
    ]


def list_my_leave_requests(service: LeaveService, actor: UserContext) -> list[dict]:
    """List the employee's own leave requests, most recent first."""
    _require_employee_access(actor)
    requests = _call_service(service.list_my_requests, actor)
    return [_serialize_request(r, _leave_type_name(service, r.leave_type_id)) for r in requests]


def get_leave_request(service: LeaveService, actor: UserContext, *, leave_request_id: uuid.UUID) -> dict:
    """Fetch one of the employee's own leave requests by id."""
    _require_employee_access(actor)
    request = _call_service(service.get_my_request, actor, leave_request_id)
    if request is None:
        raise ToolError("I couldn't find a leave request with that id.")
    return _serialize_request(request, _leave_type_name(service, request.leave_type_id))


# ---- write tools (confirmation required by agent.py before calling) -------


def submit_leave_request(
    service: LeaveService,
    actor: UserContext,
    *,
    leave_type_name: str,
    start_date: date,
    end_date: date,
    reason: str | None = None,
) -> dict:
    """Submit a new leave request. Caller (agent.py) must have already staged
    and confirmed this action with the user before invoking it."""
    _require_employee_access(actor)
    leave_type = _resolve_leave_type(service, leave_type_name)
    request = _call_service(
        service.request_leave,
        actor,
        leave_type_id=leave_type.leave_type_id,
        start_date=start_date,
        end_date=end_date,
        reason=reason,
    )
    return _serialize_request(request, leave_type.leave_name)


def cancel_leave_request(service: LeaveService, actor: UserContext, *, leave_request_id: uuid.UUID) -> dict:
    """Cancel one of the employee's own still-pending leave requests. Caller
    (agent.py) must have already staged and confirmed this with the user."""
    _require_employee_access(actor)
    request = _call_service(service.cancel_request, actor, leave_request_id)
    return _serialize_request(request, _leave_type_name(service, request.leave_type_id))


# ---- deterministic reply formatting ----------------------------------------
#
# Used for EVERY tool call the agent actually executes, read or write. The
# model's own `reply` text (written before the tool ran) is never shown to
# the employee once a tool has executed — only what actually happened,
# formatted here, ever is.


def format_tool_result(tool_name: str, result: Any) -> str:
    if tool_name == "get_leave_balance":
        if not result:
            return "You have no leave balance records for this year."
        lines = [f"{r['leave_type_name']}: {r['remaining_days']} of {r['allocated_days']} days remaining" for r in result]
        return "Your leave balance:\n" + "\n".join(lines)

    if tool_name == "list_leave_types":
        if not result:
            return "There are no active leave types configured."
        lines = [f"{t['leave_name']}{' (unpaid)' if not t['is_paid'] else ''}" for t in result]
        return "Available leave types:\n" + "\n".join(lines)

    if tool_name == "list_my_leave_requests":
        if not result:
            return "You have no leave requests."
        lines = [
            f"{r['request_number']}: {r['leave_type_name']}, {r['start_date']} to {r['end_date']} — {r['status']}"
            for r in result
        ]
        return "Your leave requests:\n" + "\n".join(lines)

    if tool_name == "get_leave_request":
        return (
            f"{result['request_number']}: {result['leave_type_name']}, "
            f"{result['start_date']} to {result['end_date']} ({result['total_days']} day(s)) — {result['status']}"
        )

    if tool_name == "submit_leave_request":
        return (
            f"Done — submitted {result['leave_type_name']} request {result['request_number']} "
            f"for {result['start_date']} to {result['end_date']} ({result['total_days']} day(s)). "
            f"Status: {result['status']}."
        )

    if tool_name == "cancel_leave_request":
        return f"Done — cancelled request {result['request_number']}. Status: {result['status']}."

    return "Done."


# ---- tool registry ----------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any]
    requires_confirmation: bool


TOOLS: dict[str, ToolSpec] = {
    "get_leave_balance": ToolSpec(
        name="get_leave_balance",
        description="Get the employee's remaining leave balance per leave type.",
        parameters={"year": "integer, optional — defaults to the current year"},
        handler=get_leave_balance,
        requires_confirmation=False,
    ),
    "list_leave_types": ToolSpec(
        name="list_leave_types",
        description="List the leave types available to request (Annual, Sick, ...).",
        parameters={},
        handler=list_leave_types,
        requires_confirmation=False,
    ),
    "list_my_leave_requests": ToolSpec(
        name="list_my_leave_requests",
        description="List the employee's own past and pending leave requests.",
        parameters={},
        handler=list_my_leave_requests,
        requires_confirmation=False,
    ),
    "get_leave_request": ToolSpec(
        name="get_leave_request",
        description="Get the status/details of one specific leave request by id.",
        parameters={"leave_request_id": "string (UUID), required"},
        handler=get_leave_request,
        requires_confirmation=False,
    ),
    "submit_leave_request": ToolSpec(
        name="submit_leave_request",
        description="Submit a new leave request. Requires explicit user confirmation first.",
        parameters={
            "leave_type_name": "string, required — e.g. 'Annual Leave', 'Sick'",
            "start_date": "string (YYYY-MM-DD), required",
            "end_date": "string (YYYY-MM-DD), required",
            "reason": "string, optional",
        },
        handler=submit_leave_request,
        requires_confirmation=True,
    ),
    "cancel_leave_request": ToolSpec(
        name="cancel_leave_request",
        description="Cancel one of the employee's own pending leave requests. Requires explicit user confirmation first.",
        parameters={"leave_request_id": "string (UUID), required"},
        handler=cancel_leave_request,
        requires_confirmation=True,
    ),
}