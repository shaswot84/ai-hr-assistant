"""Leave Agent tools: service-backed wrappers around LeaveService.

Two tool families, distinguished by role:

- Self-service tools (EMPLOYEE accounts only): balance, submit, list, get,
  cancel. No tool below accepts an employee_id argument at all — every
  LeaveService call resolves "own employee" from `actor` via
  IdentityService. It isn't a role check that could be misconfigured; it's
  structural (the parameter doesn't exist), and the extra="forbid" Pydantic
  schemas below mean a model that hallucates an employee_id argument gets a
  validation error, not a silent bypass.

- Manager tools (HR_ADMIN only, acting on employees' leave): list all
  employees' requests, view any employee's balance by employee code, and
  approve or reject any employee's pending request. Requests are
  referenced by their human-readable LR-YYYY-XXX number, never an internal
  UUID — the number the employee sees and repeats in chat. Cancelling a
  request is the employee's own action; administrators cannot cancel.

HR administrators have no employee record and no leave of their own: the
self-service tools are deliberately NOT available to them (they cannot
apply for leave or view "their" balance/requests), and candidates
(CANDIDATE) are not allowed any leave tool at all — every tool passes
through a role gate that rejects both in plain language.

Every service call goes through `_call_service`, so IdentityError,
PermissionError_, and ValueError are ALWAYS converted to ToolError — the
agent relays str(err) plainly and never leaks an internal exception type
or traceback to the user.
"""

from __future__ import annotations

import inspect
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from openinference.semconv.trace import SpanAttributes
from pydantic import BaseModel, ConfigDict, ValidationError

from app.capabilities.leave import LeaveService, PermissionError_
from app.contracts.auth import UserContext
from app.domain.leave import LeaveRequest, LeaveType
from app.observability import trace_tool_call
from app.services.identity import IdentityError


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
    """Defensive role gate for the self-service tools, independent of whatever
    route called this tool.

    Self-service leave (balance, apply, own requests) exists only for
    EMPLOYEE accounts. HR administrators have no employee record and no
    leave of their own — their tools act on employees' requests, and a
    manager asking for "my" balance or applying for leave gets a plain
    explanation, not an identity error. Candidates get no leave tools at
    all.
    """
    if actor.coarse_role == "EMPLOYEE":
        return
    if actor.coarse_role == "HR_ADMIN":
        raise ToolError(
            "As an HR administrator you can review employees' leave requests "
            "and approve, reject, or cancel them — but you don't have your own "
            "leave to apply for or view."
        )
    raise ToolError(
        "Leave requests are only available to employees. "
        "This account isn't linked to an employee record."
    )


def _require_hr_access(actor: UserContext) -> None:
    """Gate for the manager tools: only HR_ADMIN may act on another
    employee's leave or view another employee's balance."""
    if actor.coarse_role != "HR_ADMIN":
        raise ToolError(
            "Only HR administrators can review or act on another employee's leave."
        )


async def _call_service(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Call a LeaveService method with uniform exception translation and tracing."""
    tool_name = getattr(fn, "__name__", "leave_tool")
    async with trace_tool_call(tool_name, parameters=kwargs) as span:
        try:
            res = fn(*args, **kwargs)
            if inspect.isawaitable(res):
                res = await res
            span.set_attribute(SpanAttributes.OUTPUT_VALUE, str(res)[:1000])
            return res
        except (IdentityError, PermissionError_, ValueError) as err:
            span.set_attribute("tool.error", str(err))
            raise ToolError(str(err)) from err


# ---- per-tool argument schemas ---------------------------------------------


class _StrictArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


class GetLeaveBalanceArgs(_StrictArgs):
    year: int | None = None
    leave_type_name: str | None = None


class ListLeaveTypesArgs(_StrictArgs):
    pass


class ListLeaveRequestsArgs(_StrictArgs):
    pass


class ListMyLeaveRequestsArgs(_StrictArgs):
    pass


class GetLeaveRequestArgs(_StrictArgs):
    leave_request_id: uuid.UUID


class SubmitLeaveRequestArgs(_StrictArgs):
    leave_type_name: str
    start_date: date
    end_date: date
    is_half_day: bool = False
    half_day_period: str | None = None
    reason: str | None = None


class CancelLeaveRequestArgs(_StrictArgs):
    request_number: str


class GetEmployeeLeaveBalanceArgs(_StrictArgs):
    employee_code: str
    year: int | None = None


class DecideLeaveRequestArgs(_StrictArgs):
    request_number: str
    approve: bool


class ListAllEmployeeBalancesArgs(_StrictArgs):
    year: int | None = None


class ListCompanyHolidaysArgs(_StrictArgs):
    year: int | None = None


class GetTeamOutOfOfficeArgs(_StrictArgs):
    start_date: date | None = None
    end_date: date | None = None
    department_id: uuid.UUID | None = None


_ARGS_MODELS: dict[str, type[_StrictArgs]] = {
    "get_leave_balance": GetLeaveBalanceArgs,
    "list_leave_types": ListLeaveTypesArgs,
    "list_leave_requests": ListLeaveRequestsArgs,
    "list_my_leave_requests": ListMyLeaveRequestsArgs,
    "get_leave_request": GetLeaveRequestArgs,
    "submit_leave_request": SubmitLeaveRequestArgs,
    "cancel_leave_request": CancelLeaveRequestArgs,
    "get_employee_leave_balance": GetEmployeeLeaveBalanceArgs,
    "list_all_employee_balances": ListAllEmployeeBalancesArgs,
    "decide_leave_request": DecideLeaveRequestArgs,
    "list_company_holidays": ListCompanyHolidaysArgs,
    "get_team_out_of_office": GetTeamOutOfOfficeArgs,
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
    return _validate(tool_name, raw_args).model_dump(mode="python")


def canonical_args(tool_name: str, raw_args: dict[str, Any]) -> dict[str, Any]:
    return _validate(tool_name, raw_args).model_dump(mode="json")


# ---- leave-type name resolution --------------------------------------------

_LEAVE_TYPE_ALIASES: dict[str, str] = {
    "pto": "annual leave",
    "vacation": "annual leave",
    "holiday": "annual leave",
    "sick day": "sick leave",
    "sick days": "sick leave",
}


async def _resolve_leave_type(service: LeaveService, leave_type_name: str) -> LeaveType:
    types = await service.list_leave_types()
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
    if token_matches:
        raise ToolError(
            f"'{leave_type_name}' matches more than one leave type "
            f"({', '.join(t.leave_name for t in token_matches)}). Which one did you mean?"
        )
    raise ToolError(
        f"I don't see a leave type called '{leave_type_name}'. Available types: {available}."
    )


# ---- result serialization / deterministic formatting -----------------------


async def _serialize_request(
    request: LeaveRequest,
    leave_type_name: str,
    service: LeaveService | None = None,
    include_employee: bool = False,
) -> dict[str, Any]:
    data: dict[str, Any] = {
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
    if include_employee and service is not None:
        try:
            from app.domain.identity import Employee, Person
            employee = await service._db.get(Employee, request.employee_id)
            if employee is not None:
                data["employee_code"] = employee.employee_code
                person = await service._db.get(Person, employee.person_id)
                if person is not None:
                    data["employee_name"] = f"{person.first_name} {person.last_name}".strip()
                    data["employee_email"] = person.email
        except Exception:  # noqa: BLE001, S110
            pass
    return data


async def _leave_type_name(service: LeaveService, leave_type_id: uuid.UUID) -> str:
    leave_type = await service._leave_types.get(leave_type_id)
    return leave_type.leave_name if leave_type else "Unknown"


async def preflight_submit(
    service: LeaveService,
    actor: UserContext,
    *,
    leave_type_name: str,
    start_date: date,
    end_date: date,
    is_half_day: bool = False,
    half_day_period: str | None = None,
) -> tuple[Decimal, list[Any]]:
    _require_employee_access(actor)
    if end_date < start_date:
        raise ToolError("End date must be on or after the start date.")
    leave_type = await _resolve_leave_type(service, leave_type_name)
    await _call_service(
        service.check_request_conflicts,
        actor,
        leave_type_id=leave_type.leave_type_id,
        start_date=start_date,
        end_date=end_date,
        is_half_day=is_half_day,
        half_day_period=half_day_period,
    )

    rows = await _call_service(service.list_my_balance, actor, start_date.year)
    row = next((r for r in rows if r["leave_type"].leave_type_id == leave_type.leave_type_id), None)
    if row is None:
        raise ToolError(
            f"You don't have a {leave_type.leave_name} balance for {start_date.year}."
        )
    remaining = row["remaining_days"]
    try:
        total_days, holidays_in_range = await _call_service(
            service.calculate_working_days,
            start_date,
            end_date,
            is_half_day=is_half_day,
            half_day_period=half_day_period,
        )
    except ValueError as err:
        raise ToolError(str(err)) from err

    if total_days <= Decimal(0):
        if holidays_in_range:
            h_details = [
                f"'{h.name}' ({'annual recurring holiday' if h.is_recurring_yearly else 'custom company holiday created by the company'})"
                for h in holidays_in_range
            ]
            raise ToolError(
                f"You do not need to apply for leave: the requested date(s) ({start_date}{f' to {end_date}' if start_date != end_date else ''}) "
                f"fall on official company holiday: {'; '.join(h_details)}. The office is closed on this day and 0 leave days will be deducted."
            )
        raise ToolError(
            f"The requested dates ({start_date} to {end_date}) fall entirely on weekends. No leave days will be deducted."
        )

    if total_days > remaining:
        raise ToolError(
            f"Not enough {leave_type.leave_name} balance: "
            f"{remaining} day(s) remaining, {total_days} requested."
        )
    return total_days, holidays_in_range


async def mentioned_leave_type(service: LeaveService, text: str) -> str | None:
    types = await service.list_leave_types()
    if not types:
        return None
    lower_text = text.lower()
    text_tokens = set(lower_text.split())

    matches = [
        t
        for t in types
        if t.leave_name.lower() in lower_text
        or (text_tokens and text_tokens <= set(t.leave_name.lower().split()))
    ]
    return matches[0].leave_name if len(matches) == 1 else None


# ---- reference-based write preflight (deterministic staging) ---------------


async def preflight_cancel(service: LeaveService, actor: UserContext, request_number: str) -> None:
    _require_employee_access(actor)
    request = await _call_service(service.get_my_request_by_reference, actor, request_number)
    if request.status != "PENDING":
        raise ToolError(f"Only pending requests can be cancelled (status={request.status}).")


async def preflight_hr_reference(service: LeaveService, actor: UserContext, request_number: str) -> LeaveRequest:
    _require_hr_access(actor)
    request = await _call_service(service.get_request_by_number, actor, request_number)
    if request.status != "PENDING":
        raise ToolError(
            f"Only pending requests can be decided (status={request.status})."
        )
    return request


async def pending_request_lines(service: LeaveService, actor: UserContext) -> list[str]:
    requests = await _call_service(service.list_my_requests, actor)
    pending = [r for r in requests if r.status == "PENDING"]
    lines = []
    for r in pending:
        t_name = await _leave_type_name(service, r.leave_type_id)
        lines.append(f"{r.request_number}: {t_name}, {r.start_date} to {r.end_date}")
    return lines


async def hr_pending_request_lines(service: LeaveService, actor: UserContext) -> list[str]:
    _require_hr_access(actor)
    requests = await _call_service(service.list_all_requests, actor)
    pending = [r for r in requests if r.status == "PENDING"]
    lines = []
    for r in pending:
        t_name = await _leave_type_name(service, r.leave_type_id)
        lines.append(f"{r.request_number}: {t_name}, {r.start_date} to {r.end_date}")
    return lines


# ---- read tools (no confirmation) -----------------------------------------


async def get_leave_balance(
    service: LeaveService,
    actor: UserContext,
    *,
    year: int | None = None,
    leave_type_name: str | None = None,
) -> list[dict]:
    _require_employee_access(actor)
    rows = await _call_service(service.list_my_balance, actor, year)
    serialized = [
        {
            "leave_type_name": row["leave_type"].leave_name,
            "year": row["year"],
            "allocated_days": str(row["allocated_days"]),
            "used_days": str(row["used_days"]),
            "remaining_days": str(row["remaining_days"]),
        }
        for row in rows
    ]
    if leave_type_name:
        needle = leave_type_name.strip().lower()
        serialized = [r for r in serialized if r["leave_type_name"].lower() == needle]
    return serialized


async def list_leave_types(service: LeaveService, actor: UserContext) -> list[dict]:
    _require_employee_access(actor)
    types = await _call_service(service.list_leave_types)
    return [
        {
            "leave_name": t.leave_name,
            "description": t.description,
            "is_paid": t.is_paid,
            "max_consecutive_days": t.max_consecutive_days,
        }
        for t in types
    ]


async def list_my_leave_requests(service: LeaveService, actor: UserContext) -> list[dict]:
    _require_employee_access(actor)
    requests = await _call_service(service.list_my_requests, actor)
    results = []
    for r in requests:
        t_name = await _leave_type_name(service, r.leave_type_id)
        results.append(await _serialize_request(r, t_name, service=service))
    return results


async def list_leave_requests(service: LeaveService, actor: UserContext) -> list[dict]:
    _require_hr_access(actor)
    requests = await _call_service(service.list_all_requests, actor)
    results = []
    for r in requests:
        t_name = await _leave_type_name(service, r.leave_type_id)
        results.append(await _serialize_request(r, t_name, service=service, include_employee=True))
    return results


async def get_leave_request(service: LeaveService, actor: UserContext, *, leave_request_id: uuid.UUID) -> dict:
    _require_employee_access(actor)
    request = await _call_service(service.get_my_request, actor, leave_request_id)
    if request is None:
        raise ToolError("I couldn't find a leave request with that id.")
    t_name = await _leave_type_name(service, request.leave_type_id)
    return await _serialize_request(request, t_name, service=service)


# ---- write tools (confirmation required by agent.py before calling) -------


async def submit_leave_request(
    service: LeaveService,
    actor: UserContext,
    *,
    leave_type_name: str,
    start_date: date,
    end_date: date,
    is_half_day: bool = False,
    half_day_period: str | None = None,
    reason: str | None = None,
) -> dict:
    _require_employee_access(actor)
    leave_type = await _resolve_leave_type(service, leave_type_name)
    request = await _call_service(
        service.request_leave,
        actor,
        leave_type_id=leave_type.leave_type_id,
        start_date=start_date,
        end_date=end_date,
        is_half_day=is_half_day,
        half_day_period=half_day_period,
        reason=reason,
    )
    return await _serialize_request(request, leave_type.leave_name, service=service)


async def list_company_holidays(
    service: LeaveService,
    actor: UserContext,
    *,
    year: int | None = None,
) -> list[dict]:
    holidays = await _call_service(service.list_company_holidays, year)
    return [
        {
            "name": h.name,
            "holiday_date": h.holiday_date.isoformat(),
            "description": h.description,
            "is_recurring_yearly": h.is_recurring_yearly,
        }
        for h in holidays
    ]


async def get_team_out_of_office(
    service: LeaveService,
    actor: UserContext,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    department_id: uuid.UUID | None = None,
) -> list[dict]:
    entries = await _call_service(
        service.list_team_out_of_office,
        actor,
        start_date=start_date,
        end_date=end_date,
        department_id=department_id,
    )
    return [
        {
            "employee_name": e["employee_name"],
            "department_name": e["department_name"],
            "leave_type_name": e["leave_type_name"],
            "start_date": e["start_date"].isoformat(),
            "end_date": e["end_date"].isoformat(),
            "total_days": str(e["total_days"]),
            "is_half_day": e["is_half_day"],
            "half_day_period": e["half_day_period"],
            "status": e["status"],
        }
        for e in entries
    ]


async def cancel_leave_request(
    service: LeaveService, actor: UserContext, *, request_number: str
) -> dict:
    _require_employee_access(actor)
    request = await _call_service(service.cancel_request_by_reference, actor, request_number)
    t_name = await _leave_type_name(service, request.leave_type_id)
    return await _serialize_request(request, t_name, service=service)


async def get_employee_leave_balance(
    service: LeaveService,
    actor: UserContext,
    *,
    employee_code: str,
    year: int | None = None,
) -> list[dict]:
    _require_hr_access(actor)
    rows = await _call_service(service.get_employee_balance, actor, employee_code, year)
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


async def list_all_employee_balances(
    service: LeaveService,
    actor: UserContext,
    *,
    year: int | None = None,
) -> list[dict]:
    _require_hr_access(actor)
    return await _call_service(service.list_all_employee_balances, actor, year)


async def decide_leave_request(
    service: LeaveService,
    actor: UserContext,
    *,
    request_number: str,
    approve: bool,
) -> dict:
    _require_hr_access(actor)
    request = await _call_service(
        service.decide_request_by_reference, actor, request_number, approve=approve
    )
    t_name = await _leave_type_name(service, request.leave_type_id)
    return await _serialize_request(request, t_name, service=service, include_employee=True)


# ---- deterministic reply formatting ----------------------------------------


def format_tool_result(tool_name: str, result: Any) -> str:
    if tool_name in ("get_leave_balance", "get_employee_leave_balance"):
        if not result:
            return "You have no leave balance records for this year."
        lines = [f"{r['leave_type_name']}: {r['remaining_days']} of {r['allocated_days']} days remaining" for r in result]
        return "Your leave balance:\n" + "\n".join(lines)

    if tool_name == "list_all_employee_balances":
        if not result:
            return "There are no employee leave balance records found."
        lines = []
        for emp in result:
            b_str = ", ".join(f"{b['leave_type_name']}: {b['remaining_days']}/{b['allocated_days']} left" for b in emp.get("balances", []))
            lines.append(f"- {emp['employee_name']} ({emp['employee_code']}): {b_str}")
        return "Employee leave balances:\n" + "\n".join(lines)

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

    if tool_name == "list_leave_requests":
        if not result:
            return "There are no leave requests."
        lines = [
            f"{r['request_number']}: {r['leave_type_name']}, {r['start_date']} to {r['end_date']} — {r['status']}"
            for r in result
        ]
        return "Leave requests:\n" + "\n".join(lines)

    if tool_name == "get_leave_request":
        return (
            f"{result['request_number']}: {result['leave_type_name']}, "
            f"{result['start_date']} to {result['end_date']} ({result['total_days']} day(s)) — {result['status']}"
        )

    if tool_name == "list_company_holidays":
        if not result:
            return "There are no official company holidays scheduled."
        lines = [f"• **{h['name']}**: {h['holiday_date']}" + (f" ({h['description']})" if h.get('description') else "") for h in result]
        return "Official Company Holidays:\n" + "\n".join(lines)

    if tool_name == "get_team_out_of_office":
        if not result:
            return "No team members are currently scheduled out of office."
        lines = []
        for e in result:
            dur = f"{e['total_days']} day(s)"
            if e.get("is_half_day") and e.get("half_day_period"):
                dur = f"0.5 day ({e['half_day_period'].lower()})"
            lines.append(f"• **{e['employee_name']}** ({e.get('department_name') or 'Team'}): {e['leave_type_name']} from {e['start_date']} to {e['end_date']} ({dur}) — {e['status']}")
        return "Team Out of Office:\n" + "\n".join(lines)

    if tool_name == "submit_leave_request":
        dur = f"{result['total_days']} day(s)"
        if result.get("is_half_day") and result.get("half_day_period"):
            dur = f"0.5 day ({result['half_day_period'].lower()})"
        return (
            f"Done — submitted {result['leave_type_name']} request {result['request_number']} "
            f"for {result['start_date']} to {result['end_date']} ({dur}). "
            f"Status: {result['status']}."
        )

    if tool_name == "cancel_leave_request":
        return f"Done — cancelled request {result['request_number']}. Status: {result['status']}."

    if tool_name == "decide_leave_request":
        verb = "approved" if result["status"] == "APPROVED" else "rejected"
        return f"Done — {verb} request {result['request_number']}. Status: {result['status']}."

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
        description="Get the employee's remaining leave balance per leave type; pass leave_type_name to check one specific type.",
        parameters={
            "year": "integer, optional — defaults to the current year",
            "leave_type_name": "string, optional — e.g. 'Unpaid Leave'; returns only that type's row",
        },
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
    "list_leave_requests": ToolSpec(
        name="list_leave_requests",
        description="List all employees' leave requests with their statuses (HR administrators only).",
        parameters={},
        handler=list_leave_requests,
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
            "is_half_day": "boolean, optional — true if half day",
            "half_day_period": "string, optional — 'MORNING' or 'AFTERNOON'",
            "reason": "string, optional",
        },
        handler=submit_leave_request,
        requires_confirmation=True,
    ),
    "cancel_leave_request": ToolSpec(
        name="cancel_leave_request",
        description="Cancel one of the employee's own pending leave requests, identified by its request number (e.g. 'LR-2026-001'). Requires explicit user confirmation first.",
        parameters={"request_number": "string, required — e.g. 'LR-2026-001'"},
        handler=cancel_leave_request,
        requires_confirmation=True,
    ),
    "get_employee_leave_balance": ToolSpec(
        name="get_employee_leave_balance",
        description="Get another employee's remaining leave balance per leave type, identified by employee code (HR administrators only).",
        parameters={
            "employee_code": "string, required — the employee's code, e.g. 'EMP-001'",
            "year": "integer, optional — defaults to the current year",
        },
        handler=get_employee_leave_balance,
        requires_confirmation=False,
    ),
    "list_all_employee_balances": ToolSpec(
        name="list_all_employee_balances",
        description="List all active employees' leave balances across all leave types (HR administrators only).",
        parameters={
            "year": "integer, optional — defaults to the current year",
        },
        handler=list_all_employee_balances,
        requires_confirmation=False,
    ),
    "decide_leave_request": ToolSpec(
        name="decide_leave_request",
        description="Approve or reject any employee's pending leave request by request number (HR administrators only). Requires explicit user confirmation first.",
        parameters={
            "request_number": "string, required — e.g. 'LR-2026-001'",
            "approve": "boolean, required — true to approve, false to reject",
        },
        handler=decide_leave_request,
        requires_confirmation=True,
    ),
    "list_company_holidays": ToolSpec(
        name="list_company_holidays",
        description="List official company holidays and office closures.",
        parameters={"year": "integer, optional — defaults to current year"},
        handler=list_company_holidays,
        requires_confirmation=False,
    ),
    "get_team_out_of_office": ToolSpec(
        name="get_team_out_of_office",
        description="Check who is out of office in the team / department for upcoming dates.",
        parameters={
            "start_date": "string (YYYY-MM-DD), optional",
            "end_date": "string (YYYY-MM-DD), optional",
        },
        handler=get_team_out_of_office,
        requires_confirmation=False,
    ),
}