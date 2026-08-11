from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.capabilities.leave import LeaveService, PermissionError_
from app.domain.outbox import OutboxJob


def _create_leave_type(
    svc,
    actor,
    *,
    name="Annual Leave",
    default_days=Decimal(20),
    max_consecutive_days=None,
):
    return svc.create_leave_type(
        actor,
        leave_name=name,
        description="Planned time off.",
        default_days=default_days,
        requires_approval=True,
        is_paid=True,
        max_consecutive_days=max_consecutive_days,
    )


def test_create_leave_type_requires_hr_admin(db, employee_context):
    svc = LeaveService(db)
    with pytest.raises(PermissionError_):
        _create_leave_type(svc, employee_context)


def test_create_leave_type_success(db, manager_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    assert leave_type.status == "ACTIVE"
    assert leave_type in svc.list_leave_types()


def test_balance_defaults_to_leave_type_default_before_any_request(db, manager_context, employee_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, default_days=Decimal(12))

    rows = svc.list_my_balance(employee_context)
    assert len(rows) == 1
    assert rows[0]["allocated_days"] == Decimal(12)
    assert rows[0]["used_days"] == Decimal(0)
    assert rows[0]["remaining_days"] == Decimal(12)


def test_request_leave_requires_employee_or_hr_admin(db, manager_context, candidate_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    with pytest.raises(PermissionError_):
        svc.request_leave(
            candidate_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 2),
            reason=None,
        )


def test_request_leave_rejects_end_before_start(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    with pytest.raises(ValueError, match="on or after"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 5),
            end_date=date(2026, 9, 1),
            reason=None,
        )


def test_request_leave_enforces_max_consecutive_days(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, max_consecutive_days=3)
    with pytest.raises(ValueError, match="consecutive"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),  # 5 days, over the 3-day cap
            reason=None,
        )


def test_request_leave_enforces_remaining_balance(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(2))
    with pytest.raises(ValueError, match="Not enough"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),  # 5 days requested, only 2 allocated
            reason=None,
        )


def test_request_leave_success_generates_sequential_reference(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)

    first = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        reason="Family event",
    )
    assert first.status == "PENDING"
    assert first.total_days == Decimal(2)
    assert first.request_number.startswith(f"LR-{date(2026, 9, 1).year}-")

    second = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 10, 1),
        end_date=date(2026, 10, 1),
        reason=None,
    )
    assert second.request_number != first.request_number


def test_request_leave_enqueues_confirmation_and_manager_alert(db, manager_context, employee_context):
    """No org hierarchy is configured for `employee_context`, so the alert
    should fall back to the seeded HR_ADMIN rather than being dropped.
    """
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        reason=None,
    )

    jobs = db.scalars(
        select(OutboxJob).where(OutboxJob.aggregate_id == request.leave_request_id)
    ).all()
    by_type = {j.job_type: j for j in jobs}

    assert "SEND_LEAVE_REQUEST_RECEIVED" in by_type
    assert by_type["SEND_LEAVE_REQUEST_RECEIVED"].payload["to_email"] == employee_context.email

    assert "SEND_NEW_LEAVE_REQUEST_ALERT" in by_type
    assert by_type["SEND_NEW_LEAVE_REQUEST_ALERT"].payload["to_email"] == manager_context.email


def test_cancel_request_only_from_pending(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        reason=None,
    )
    svc.decide_request(manager_context, request.leave_request_id, approve=True)

    with pytest.raises(ValueError, match="Only pending requests"):
        svc.cancel_request(employee_context, request.leave_request_id)


def test_cancel_request_success(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        reason=None,
    )
    cancelled = svc.cancel_request(employee_context, request.leave_request_id)
    assert cancelled.status == "CANCELLED"


def test_list_all_requests_requires_hr_admin(db, employee_context):
    svc = LeaveService(db)
    with pytest.raises(PermissionError_):
        svc.list_all_requests(employee_context)


def test_decide_request_approve_books_balance_then_redecide_is_blocked(
    db, manager_context, employee_context
):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(10))
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),  # 3 days
        reason=None,
    )

    decided = svc.decide_request(manager_context, request.leave_request_id, approve=True)
    assert decided.status == "APPROVED"

    rows = svc.list_my_balance(employee_context, year=2026)
    row = next(r for r in rows if r["leave_type"].leave_type_id == leave_type.leave_type_id)
    assert row["used_days"] == Decimal(3)
    assert row["remaining_days"] == Decimal(7)

    # Regression guard, mirrors recruitment's decide-twice test: once decided,
    # a request is terminal — re-deciding must never double-book the balance
    # or re-send the outcome email.
    with pytest.raises(ValueError, match="already been decided"):
        svc.decide_request(manager_context, request.leave_request_id, approve=False)


def test_decide_request_reject_does_not_touch_balance(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(10))
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason=None,
    )

    decided = svc.decide_request(manager_context, request.leave_request_id, approve=False)
    assert decided.status == "REJECTED"

    rows = svc.list_my_balance(employee_context, year=2026)
    row = next(r for r in rows if r["leave_type"].leave_type_id == leave_type.leave_type_id)
    assert row["used_days"] == Decimal(0)


def test_create_leave_type_http_requires_hr_admin(client, employee_context, employee_password):
    login = client.post(
        "/api/auth/login",
        json={"email": employee_context.email, "password": employee_password},
    )
    token = login.json()["access_token"]
    res = client.post(
        "/api/leave/types",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "leave_name": "Should Not Be Created",
            "default_days": "5",
            "is_paid": True,
        },
    )
    assert res.status_code == 403


def test_leave_request_http_flow(db, client, manager_context, employee_context, employee_password, manager_password):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)

    login = client.post(
        "/api/auth/login",
        json={"email": employee_context.email, "password": employee_password},
    )
    token = login.json()["access_token"]

    start = date.today() + timedelta(days=7)
    end = start + timedelta(days=1)
    res = client.post(
        "/api/leave/requests",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "leave_type_id": str(leave_type.leave_type_id),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "reason": "Trip",
        },
    )
    assert res.status_code == 201
    request_id = res.json()["leave_request_id"]

    mine = client.get("/api/leave/requests/mine", headers={"Authorization": f"Bearer {token}"})
    assert mine.status_code == 200
    assert any(r["leave_request_id"] == request_id for r in mine.json())

    mgr_login = client.post(
        "/api/auth/login",
        json={"email": manager_context.email, "password": manager_password},
    )
    mgr_token = mgr_login.json()["access_token"]
    decision = client.post(
        f"/api/leave/requests/{request_id}/decision",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={"action": "approve"},
    )
    assert decision.status_code == 200
    assert decision.json()["status"] == "APPROVED"
    assert decision.json()["employee_email"] == employee_context.email
