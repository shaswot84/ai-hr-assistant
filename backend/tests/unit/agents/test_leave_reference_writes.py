"""Leave Agent: deterministic cancel-by-reference and HR manager tools.

Cancels, approvals, and rejections are staged by request NUMBER (LR-YYYY-XXX),
resolved by code — never invented by the model. Employees get a self-service
cancel flow (asking which request when no reference is given); HR_ADMIN gets
balance view, decide, and cancel tools for any employee's leave. CANDIDATE is
blocked from every leave tool.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.agents.leave_agent.agent import handle_turn
from app.agents.leave_agent.state import DraftRequest, LeaveAgentState
from app.capabilities.leave import LeaveService
from app.contracts.auth import UserContext
from app.domain.leave import LeaveRequest
from app.shared.clock import get_clock


def _create_leave_type(svc, actor, *, name="Annual Leave", default_days=Decimal(20)):
    return svc.create_leave_type(
        actor,
        leave_name=name,
        description="Planned time off.",
        default_days=default_days,
        requires_approval=True,
        is_paid=True,
        max_consecutive_days=None,
    )


def _state(actor) -> LeaveAgentState:
    now = get_clock().now()
    return LeaveAgentState(
        session_id="sess-1",
        actor_subject=actor.subject,
        created_at=now,
        updated_at=now,
    )


class FakeChatProvider:
    """A ChatProvider stub returning canned JSON (no real model)."""

    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls = 0

    async def complete_json(self, **kwargs) -> dict:
        self.calls += 1
        return self.payload


def _seed_pending_request(svc, manager_ctx, employee_ctx) -> LeaveRequest:
    """A real PENDING request for the seeded employee (leave types are
    manager-only)."""
    leave_type = _create_leave_type(svc, manager_ctx)
    today = get_clock().today()
    return svc.request_leave(
        employee_ctx,
        leave_type_id=leave_type.leave_type_id,
        start_date=today + timedelta(days=5),
        end_date=today + timedelta(days=6),
        reason=None,
    )


def _request_count(db) -> int:
    return len(db.scalars(select(LeaveRequest)).all())


def _seed_second_employee(db) -> UserContext:
    """A second, distinct EMPLOYEE identity (someone else's request owner)."""
    from app.auth.passwords import hash_password
    from app.domain.identity import ApplicationUser, Department, Designation, Employee, Person

    now = get_clock().now()
    person = Person(
        first_name="Bob", last_name="Worker", email="bob@acme-hr-test.dev",
        created_at=now, updated_at=now,
    )
    db.add(person)
    db.flush()
    dept = Department(name="Finance")
    db.add(dept)
    db.flush()
    desig = Designation(department_id=dept.department_id, title="Analyst")
    db.add(desig)
    db.flush()
    db.add(
        Employee(
            person_id=person.person_id,
            employee_code="EMP-TEST-002",
            department_id=dept.department_id,
            designation_id=desig.designation_id,
            joining_date=get_clock().today(),
            created_at=now,
            updated_at=now,
        )
    )
    db.add(
        ApplicationUser(
            external_subject="emp2-subject",
            person_id=person.person_id,
            coarse_role="EMPLOYEE",
            password_hash=hash_password("employee-secret-2"),
            created_at=now,
            updated_at=now,
        )
    )
    db.commit()
    return UserContext(
        subject="emp2-subject", email=person.email, display_name="Bob Worker",
        coarse_role="EMPLOYEE",
    )


# ---- employee cancel-by-reference ------------------------------------------


@pytest.mark.asyncio
async def test_cancel_without_reference_lists_pending_requests(
    db, manager_context, employee_context
):
    """"Cancel my leave request" with no reference lists what CAN be cancelled
    and asks for the number — the model is never asked to guess one."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="cancel my leave request",
    )

    assert provider.calls == 0
    assert "Which request" in result.reply
    assert "LR-" in result.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_cancel_with_no_pending_requests_replies_honestly(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="cancel my leave request",
    )

    assert provider.calls == 0
    assert "no pending leave requests" in result.reply


@pytest.mark.asyncio
async def test_cancel_by_reference_stages_then_executes(db, manager_context, employee_context):
    """A message naming the reference stages the cancel deterministically,
    and a "yes" cancels the real request through the confirmation gate."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(employee_context)

    provider = FakeChatProvider({})
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"please cancel request {request.request_number}",
    )
    assert provider.calls == 0
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool == "cancel_leave_request"
    assert state.pending_confirmation.args == {"request_number": request.request_number}
    assert f"Cancel leave request {request.request_number}" in result.reply

    confirm = FakeChatProvider(
        {
            "reply": "Cancelling.",
            "action": "call_tool",
            "tool": "cancel_leave_request",
            "args": state.pending_confirmation.args,
        }
    )
    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=confirm,
        user_message="yes",
    )

    assert confirm.calls == 1
    assert result.tool_called == "cancel_leave_request"
    refreshed = svc.get_my_request_by_reference(employee_context, request.request_number)
    assert refreshed.status == "CANCELLED"


@pytest.mark.asyncio
async def test_cancel_non_pending_request_is_rejected_before_staging(
    db, manager_context, employee_context
):
    """An already-decided request is surfaced at stage time, never staged."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    svc.decide_request(
        manager_context, request.leave_request_id, approve=True
    )
    state = _state(employee_context)
    provider = FakeChatProvider({})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"cancel request {request.request_number}",
    )

    assert provider.calls == 0
    assert "Only pending requests can be cancelled" in result.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_cancel_unknown_reference_rejected(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="cancel request LR-2026-999",
    )

    assert "not found" in result.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_cancel_other_employees_reference_rejected(db, manager_context, employee_context):
    """An employee can only cancel their OWN request — someone else's
    reference fails closed as not found."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    other = _seed_second_employee(db)
    state = _state(other)

    result = await handle_turn(
        actor=other,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="cancel request LR-2026-001",
    )

    assert "not found" in result.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_cancel_intent_message_is_never_treated_as_draft_continuation(
    db, manager_context, employee_context
):
    """A cancel-intent message must never continue an open application draft —
    even when it contains a relative date ("from tomorrow") — and the pivot
    drops the stale draft."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(employee_context)
    state.set_draft(
        DraftRequest(leave_type_name="Annual Leave", start_date=date(2026, 9, 1)),
        clock=get_clock(),
    )
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="cancel my leave request from tomorrow",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert state.pending_confirmation is None
    assert "no pending leave requests" in result.reply


@pytest.mark.asyncio
async def test_cancel_listing_clears_stale_draft_and_staged_action(
    db, manager_context, employee_context
):
    """Pivoting to cancel drops any in-progress application draft AND any
    previously staged action — a later "yes" cannot fire the stale submit."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    state = _state(employee_context)
    state.set_draft(
        DraftRequest(leave_type_name="Annual Leave", start_date=date(2026, 9, 1)),
        clock=get_clock(),
    )
    state.stage(
        "submit_leave_request",
        {
            "leave_type_name": "Annual Leave",
            "start_date": "2026-09-01",
            "end_date": "2026-09-02",
            "reason": None,
        },
        "Submit an Annual Leave request?",
        clock=get_clock(),
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="cancel one pending leave request",
    )

    assert state.draft is None
    assert state.pending_confirmation is None
    assert "Which request would you like to cancel?" in result.reply
    assert "LR-" in result.reply


@pytest.mark.asyncio
async def test_descriptive_reply_to_cancel_question_is_not_a_new_application(
    db, manager_context, employee_context
):
    """"leave which i had recently added today" is not an application: without
    request intent the draft flow stays out, the model handles the turn, and
    no draft is created."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    state = _state(employee_context)
    provider = FakeChatProvider(
        {
            "reply": "Could you reply with the request number?",
            "action": "reply",
            "tool": None,
            "args": {},
        }
    )

    result = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="leave which i had recently added today",
    )

    assert provider.calls == 1
    assert state.draft is None
    assert state.pending_confirmation is None


# ---- HR manager tools -------------------------------------------------------


@pytest.mark.asyncio
async def test_hr_approve_by_reference_stages_then_executes(
    db, manager_context, employee_context
):
    """HR "approve request LR-..." stages a deterministic decision; "yes"
    approves the real request and books the balance days."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider({})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"approve request {request.request_number}",
    )

    assert provider.calls == 0
    assert state.pending_confirmation is not None
    assert state.pending_confirmation.tool == "decide_leave_request"
    assert state.pending_confirmation.args == {
        "request_number": request.request_number,
        "approve": True,
    }
    assert f"Approve leave request {request.request_number}" in result.reply

    confirm = FakeChatProvider(
        {
            "reply": "Approving.",
            "action": "call_tool",
            "tool": "decide_leave_request",
            "args": state.pending_confirmation.args,
        }
    )
    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=confirm,
        user_message="yes",
    )

    assert confirm.calls == 1
    assert result.tool_called == "decide_leave_request"
    assert "approved" in result.reply
    refreshed = svc.get_request_by_number(manager_context, request.request_number)
    assert refreshed.status == "APPROVED"


@pytest.mark.asyncio
async def test_hr_reject_by_reference(db, manager_context, employee_context):
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message=f"reject request {request.request_number}",
    )

    assert state.pending_confirmation.args == {
        "request_number": request.request_number,
        "approve": False,
    }

    confirm = FakeChatProvider(
        {
            "reply": "Rejecting.",
            "action": "call_tool",
            "tool": "decide_leave_request",
            "args": state.pending_confirmation.args,
        }
    )
    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=confirm,
        user_message="yes",
    )

    assert "rejected" in result.reply
    assert svc.get_request_by_number(manager_context, request.request_number).status == "REJECTED"


@pytest.mark.asyncio
async def test_hr_cannot_cancel_requests(db, manager_context, employee_context):
    """Cancelling is the employee's own action: an administrator asking to
    cancel — with or without a reference — is refused deterministically and
    nothing is staged or executed."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider({})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=f"cancel request {request.request_number}",
    )

    assert provider.calls == 0
    assert "employee's own action" in result.reply
    assert state.pending_confirmation is None
    assert svc.get_request_by_number(manager_context, request.request_number).status == "PENDING"

    without = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="cancel a request",
    )
    assert "employee's own action" in without.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_hr_action_without_reference_lists_pending(db, manager_context, employee_context):
    """A manager's approve/cancel intent without a reference shows the real
    pending list to pick from — no number recall, no model guessing."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider({})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="please approve a request",
    )

    assert provider.calls == 0
    assert "pending leave requests" in result.reply
    assert "LR-2026-001" in result.reply
    assert "Reply with the request number" in result.reply
    assert state.pending_confirmation is None


@pytest.mark.asyncio
async def test_hr_lists_pending_requests_deterministically(db, manager_context, employee_context):
    """"show me the pending leave requests" is answered without the model —
    the manager sees exactly what CAN be approved/rejected/cancelled."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider({})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="show me the pending leave requests",
    )

    assert provider.calls == 0
    assert "pending leave requests" in result.reply
    assert request.request_number in result.reply
    assert "Annual Leave" in result.reply
    assert "Reply with the request number" in result.reply


@pytest.mark.asyncio
async def test_hr_no_pending_requests_reply(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(manager_context)

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="show me pending requests",
    )

    assert "no pending leave requests" in result.reply


@pytest.mark.asyncio
async def test_hr_list_all_requests_deterministic(db, manager_context, employee_context):
    """The manager's list_leave_requests read tool is executed deterministically
    — "see all requests" never reaches the model, so a model that would pick
    the near-identical list_my_leave_requests cannot derail it into the
    "you have no leave of your own" refusal."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider(
        {
            "reply": "Let me pull that up.",
            "action": "call_tool",
            "tool": "list_leave_requests",
            "args": {},
        }
    )

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="show me all leave requests",
    )

    assert provider.calls == 0
    assert result.tool_called == "list_leave_requests"
    assert request.request_number in result.reply
    assert "PENDING" in result.reply


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "message",
    [
        "can i see all the leave request?",
        "show me all leave requests",
        "list every leave request",
        "i want to view the requests",
    ],
)
async def test_hr_list_all_requests_phrasing_is_deterministic(
    db, manager_context, employee_context, message
):
    """Every request-listing phrasing for an administrator is answered
    deterministically from the manager tool — the model is never consulted
    and the "you have no leave of your own" refusal never appears."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message=message,
    )

    assert provider.calls == 0
    assert result.tool_called == "list_leave_requests"
    assert request.request_number in result.reply
    assert "PENDING" in result.reply
    assert "HR administrator" not in result.reply


@pytest.mark.asyncio
async def test_hr_list_all_recovers_when_model_picks_self_service_tool(
    db, manager_context, employee_context
):
    """A phrasing the interception does not claim (no view/all word) but that
    is still a request-listing ask: if the model calls the self-service
    list_my_leave_requests, the role-gate rejection is recovered into the
    manager list instead of the "you have no leave of your own" dead end."""
    svc = LeaveService(db)
    request = _seed_pending_request(svc, manager_context, employee_context)
    state = _state(manager_context)
    provider = FakeChatProvider(
        {
            "reply": "Listing.",
            "action": "call_tool",
            "tool": "list_my_leave_requests",
            "args": {},
        }
    )

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="what requests are there",
    )

    assert provider.calls == 1
    assert result.tool_called == "list_leave_requests"
    assert request.request_number in result.reply
    assert "HR administrator" not in result.reply


@pytest.mark.asyncio
async def test_hr_employee_balance_tool(db, manager_context, employee_context):
    """HR can read another employee's balance by employee code via the tool."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(manager_context)
    provider = FakeChatProvider(
        {
            "reply": "Checking.",
            "action": "call_tool",
            "tool": "get_employee_leave_balance",
            "args": {"employee_code": "EMP-TEST-001"},
        }
    )

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="what's the balance for EMP-TEST-001",
    )

    assert provider.calls == 1
    assert result.tool_called == "get_employee_leave_balance"
    assert "Annual Leave" in result.reply
    assert "20" in result.reply


@pytest.mark.asyncio
async def test_hr_cannot_apply_for_leave(db, manager_context, employee_context):
    """An HR administrator is refused deterministically — no draft, no model,
    no leave_request row — when they try to start an application."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(manager_context)
    provider = FakeChatProvider({"reply": "x", "action": "reply", "tool": None, "args": {}})

    result = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="i want to apply for annual leave tomorrow",
    )

    assert provider.calls == 0
    assert state.draft is None
    assert state.pending_confirmation is None
    assert "can't apply" in result.reply
    assert _request_count(db) == 0


@pytest.mark.asyncio
async def test_hr_cannot_use_self_service_tools(db, manager_context, employee_context):
    """HR has no leave of their own: a model that stages a submit or calls the
    self-service view tools for an administrator is stopped by the role gate
    with a clear message — nothing is staged or executed."""
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context)
    state = _state(manager_context)

    staged = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Let me propose that.",
                "action": "stage",
                "tool": "submit_leave_request",
                "args": {
                    "leave_type_name": "Annual Leave",
                    "start_date": "2026-09-01",
                    "end_date": "2026-09-02",
                    "reason": None,
                },
            }
        ),
        user_message="i want to apply for annual leave",
    )
    assert "HR administrator" in staged.reply
    assert state.pending_confirmation is None
    assert _request_count(db) == 0

    balance = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Checking.",
                "action": "call_tool",
                "tool": "get_leave_balance",
                "args": {},
            }
        ),
        user_message="what's my leave balance",
    )
    assert "HR administrator" in balance.reply

    mine = await handle_turn(
        actor=manager_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Listing.",
                "action": "call_tool",
                "tool": "list_my_leave_requests",
                "args": {},
            }
        ),
        # A balance ask is not a listing ask, so the self-service tool is not
        # recovered into list_leave_requests — the gate's refusal stands.
        user_message="show my leave balance",
    )
    assert "HR administrator" in mine.reply


@pytest.mark.asyncio
async def test_employee_cannot_use_hr_tools(db, manager_context, employee_context):
    """An employee gets no HR capability: the manager READ tool is rejected
    by the role gate, and a manager WRITE call never reaches the service —
    there is no staged confirmation to match."""
    svc = LeaveService(db)
    _seed_pending_request(svc, manager_context, employee_context)
    state = _state(employee_context)

    read = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Checking.",
                "action": "call_tool",
                "tool": "get_employee_leave_balance",
                "args": {"employee_code": "EMP-TEST-001"},
            }
        ),
        user_message="show me someone else's balance",
    )
    assert read.tool_called == "get_employee_leave_balance"
    assert "Only HR administrators" in read.reply

    write = await handle_turn(
        actor=employee_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider(
            {
                "reply": "Approving.",
                "action": "call_tool",
                "tool": "decide_leave_request",
                "args": {"request_number": "LR-2026-001", "approve": True},
            }
        ),
        user_message="yes",
    )
    assert "staged" in write.reply
    assert svc.get_request_by_number(manager_context, "LR-2026-001").status == "PENDING"


@pytest.mark.asyncio
async def test_candidate_blocked_from_all_leave_tools(db, candidate_context):
    """CANDIDATE is not allowed leave tools: the role gate rejects before any
    service call, whether by model tool call or by cancel intent."""
    svc = LeaveService(db)
    state = _state(candidate_context)
    provider = FakeChatProvider(
        {
            "reply": "Checking.",
            "action": "call_tool",
            "tool": "get_leave_balance",
            "args": {},
        }
    )

    result = await handle_turn(
        actor=candidate_context,
        state=state,
        service=svc,
        chat_provider=provider,
        user_message="how much leave do I have",
    )

    assert provider.calls == 1
    assert "only available to employees" in result.reply

    cancel = await handle_turn(
        actor=candidate_context,
        state=state,
        service=svc,
        chat_provider=FakeChatProvider({}),
        user_message="cancel my leave request",
    )
    assert "employees" in cancel.reply
    assert state.pending_confirmation is None