"""Leave Agent tool registry -- thin wrappers over `LeaveService`.

Every tool takes `(actor: UserContext, **args)` and calls straight into
`app.capabilities.leave.LeaveService`. No SQL, no ORM, no business rule
lives here -- see A2-backend-conventions.md Sec.3 for why that's a hard line.

Two things this module is deliberately built around:

1. `TOOLS` is a registry (name -> ToolSpec), not a chain of `if` statements.
   `prompts.py` renders the tool-choice prompt from `TOOLS[name].parameters`
   / `.description`; `agent.py` dispatches via `TOOLS[name].handler(...)`
   and checks `.requires_confirmation` to decide whether to stage-then-wait
   or execute immediately. Neither of those files needs to know these
   individual functions exist.

2. `decide_leave_request` (approve/reject someone else's request) is not a
   tool here at all -- not filtered out by a role check, just never
   defined. Per `04-leave-agent.md` Sec.2, deciding on requests is out of
   scope for the employee-facing Leave Agent regardless of whether the
   caller is a manager or HR_ADMIN. That's an agent-scope boundary,
   enforced by omission, not a permission that could be bypassed.

Role gate, three layers deep: the route (`api/routes/leave_chat.py`)
already rejects CANDIDATE via `require_role("EMPLOYEE", "HR_ADMIN")`
before the agent ever runs. This module re-checks anyway, on every tool,
because `LeaveService.get_my_request` and `.cancel_request` have no role
check of their own today -- they rely on `IdentityService.get_employee`
raising `IdentityError`, which nothing upstream of the FastAPI dependency
chain currently catches. If this agent is ever invoked from anywhere
other than that one route (a future Supervisor, a test harness, a
retried background call), an unchecked CANDIDATE would otherwise hit an
unhandled 500 instead of a clean refusal.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from difflib import get_close_matches
from typing import Any, Callable

from app.capabilities.leave import LeaveService, PermissionError_
from app.contracts.auth import UserContext
from app.services.identity import IdentityError

# Only these two roles may use ANY tool in this registry. CANDIDATE is
# blocked here even though the route already blocks it -- see module
# docstring for why this isn't considered redundant.
_ALLOWED_ROLES = ("EMPLOYEE", "HR_ADMIN")


class ToolError(Exception):
    """Raised for a clean, user-facing tool failure (bad role, bad input,
    ambiguous leave type, service-level ValueError/PermissionError_).

    `agent.py` catches this and relays `str(exc)` back to the model/user
    as a plain refusal or correction -- never as a stack trace.
    """


def _require_allowed_role(actor: UserContext) -> None:
    """Reject CANDIDATE (or any future role not explicitly allowed) before
    any service method -- or `IdentityService` -- is ever reached."""
    if actor.coarse_role not in _ALLOWED_ROLES:
        raise ToolError("This assistant only handles an employee's own leave requests.")


def _resolve_leave_type_id(service: LeaveService, leave_type_name: str) -> uuid.UUID:
    """Resolve a user-typed leave type name ("sick leave") to a real id.

    This translation belongs here, not in `LeaveService.request_leave`
    (which correctly takes a real `leave_type_id: uuid.UUID` -- the service
    should never do business-name string matching). Fails closed per
    `04-leave-agent.md`'s "ambiguous leave type" guardrail: no confident
    match raises `ToolError` listing the real options rather than guessing.
    """
    types = service.list_leave_types()
    by_name = {t.leave_name.strip().lower(): t for t in types}
    needle = leave_type_name.strip().lower()

    exact = by_name.get(needle)
    if exact is not None:
        return exact.leave_type_id

    match = get_close_matches(needle, list(by_name.keys()), n=1, cutoff=0.6)
    if match:
        return by_name[match[0]].leave_type_id

    available = ", ".join(t.leave_name for t in types) or "none configured"
    raise ToolError(
        f"I don't see a leave type called \"{leave_type_name}\". "
        f"Available types: {available}."
    )


def _serialize_request(request: Any) -> dict:
    """Shape a `LeaveRequest` ORM row into the JSON-friendly dict tools return."""
    return {
        "leave_request_id": str(request.leave_request_id),
        "request_number": request.request_number,
        "leave_type_id": str(request.leave_type_id),
        "start_date": request.start_date.isoformat(),
        "end_date": request.end_date.isoformat(),
        "total_days": str(request.total_days),
        "reason": request.reason,
        "status": request.status,
        "submitted_at": request.submitted_at.isoformat(),
    }


def _serialize_balance_row(row: dict) -> dict:
    """Shape one row of `LeaveService.list_my_balance`'s output for the tool result."""
    leave_type = row["leave_type"]
    return {
        "leave_type_id": str(leave_type.leave_type_id),
        "leave_name": leave_type.leave_name,
        "year": row["year"],
        "allocated_days": str(row["allocated_days"]),
        "used_days": str(row["used_days"]),
        "remaining_days": str(row["remaining_days"]),
    }


# ---------------------------------------------------------------------------
# Tool implementations
# ---------------------------------------------------------------------------


def list_leave_types(service: LeaveService, actor: UserContext) -> list[dict]:
    """List active leave types the employee can request against. Read-only."""
    _require_allowed_role(actor)
    return [
        {
            "leave_type_id": str(t.leave_type_id),
            "leave_name": t.leave_name,
            "description": t.description,
            "is_paid": t.is_paid,
            "requires_approval": t.requires_approval,
            "max_consecutive_days": t.max_consecutive_days,
        }
        for t in service.list_leave_types()
    ]


def get_leave_balance(service: LeaveService, actor: UserContext, *, year: int | None = None) -> list[dict]:
    """Get the caller's own allocated/used/remaining days per leave type. Read-only."""
    _require_allowed_role(actor)
    try:
        rows = service.list_my_balance(actor, year)
    except PermissionError_ as exc:
        raise ToolError(str(exc)) from exc
    return [_serialize_balance_row(r) for r in rows]


def submit_leave_request(
    service: LeaveService,
    actor: UserContext,
    *,
    leave_type_name: str,
    start_date: date,
    end_date: date,
    reason: str | None = None,
) -> dict:
    """Submit a leave request. Write -- staged and confirmed before this fires
    (see `agent.py`'s confirmation loop; `requires_confirmation=True` below)."""
    _require_allowed_role(actor)
    leave_type_id = _resolve_leave_type_id(service, leave_type_name)
    try:
        request = service.request_leave(
            actor,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            reason=reason,
        )
    except (ValueError, PermissionError_) as exc:
        raise ToolError(str(exc)) from exc
    return _serialize_request(request)


def cancel_leave_request(service: LeaveService, actor: UserContext, *, leave_request_id: str) -> dict:
    """Cancel one of the caller's own still-pending requests. Write -- confirmed first."""
    _require_allowed_role(actor)
    try:
        request = service.cancel_request(actor, uuid.UUID(leave_request_id))
    except (ValueError, PermissionError_) as exc:
        raise ToolError(str(exc)) from exc
    except IdentityError as exc:
        # capabilities/leave.py gap: cancel_request doesn't raise PermissionError_
        # itself -- caught here so a non-employee gets a clean refusal instead
        # of an unhandled 500 if this agent is ever reached without the
        # route's require_role() gate in front of it.
        raise ToolError("This assistant only handles an employee's own leave requests.") from exc
    return _serialize_request(request)


def get_leave_request(service: LeaveService, actor: UserContext, *, leave_request_id: str) -> dict:
    """Look up one of the caller's own leave requests by id. Read-only."""
    _require_allowed_role(actor)
    try:
        request = service.get_my_request(actor, uuid.UUID(leave_request_id))
    except ValueError as exc:
        raise ToolError(str(exc)) from exc
    except IdentityError as exc:
        # same gap as cancel_leave_request above.
        raise ToolError("This assistant only handles an employee's own leave requests.") from exc
    return _serialize_request(request)


def list_my_leave_requests(service: LeaveService, actor: UserContext) -> list[dict]:
    """List all of the caller's own leave requests, most recent first. Read-only."""
    _require_allowed_role(actor)
    try:
        requests = service.list_my_requests(actor)
    except PermissionError_ as exc:
        raise ToolError(str(exc)) from exc
    return [_serialize_request(r) for r in requests]


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ToolSpec:
    """One entry in the tool registry -- enough for `prompts.py` to render a
    schema and `agent.py` to dispatch, without either needing to import the
    handler functions above directly."""

    name: str
    description: str
    parameters: dict[str, Any]  # JSON-schema-ish: {param_name: {"type": ..., "required": bool, ...}}
    handler: Callable[..., Any]
    requires_confirmation: bool


TOOLS: dict[str, ToolSpec] = {
    "list_leave_types": ToolSpec(
        name="list_leave_types",
        description="List the leave types the employee can request (e.g. Annual, Sick).",
        parameters={},
        handler=list_leave_types,
        requires_confirmation=False,
    ),
    "get_leave_balance": ToolSpec(
        name="get_leave_balance",
        description="Get the employee's own remaining leave balance, optionally for a specific year.",
        parameters={
            "year": {"type": "integer", "required": False, "description": "Defaults to the current year."},
        },
        handler=get_leave_balance,
        requires_confirmation=False,
    ),
    "submit_leave_request": ToolSpec(
        name="submit_leave_request",
        description="Submit a new leave request for the employee's own account.",
        parameters={
            "leave_type_name": {"type": "string", "required": True, "description": "e.g. \"Annual\", \"Sick\""},
            "start_date": {"type": "string", "required": True, "description": "ISO date, e.g. 2026-08-17"},
            "end_date": {"type": "string", "required": True, "description": "ISO date, e.g. 2026-08-18"},
            "reason": {"type": "string", "required": False},
        },
        handler=submit_leave_request,
        requires_confirmation=True,
    ),
    "cancel_leave_request": ToolSpec(
        name="cancel_leave_request",
        description="Cancel one of the employee's own PENDING leave requests.",
        parameters={
            "leave_request_id": {"type": "string", "required": True},
        },
        handler=cancel_leave_request,
        requires_confirmation=True,
    ),
    "get_leave_request": ToolSpec(
        name="get_leave_request",
        description="Look up the status/details of one of the employee's own leave requests.",
        parameters={
            "leave_request_id": {"type": "string", "required": True},
        },
        handler=get_leave_request,
        requires_confirmation=False,
    ),
    "list_my_leave_requests": ToolSpec(
        name="list_my_leave_requests",
        description="List all of the employee's own leave requests.",
        parameters={},
        handler=list_my_leave_requests,
        requires_confirmation=False,
    ),
}

# NOTE: `decide_leave_request` (approve/reject) is intentionally absent --
# see module docstring point 2. Do not add it here; a manager/HR_ADMIN
# decision flow, if it ever gets an agent, belongs in a separate,
# manager-facing tool registry, not this one.