from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.capabilities.leave import LeaveService, PermissionError_
from app.agents.leave_agent.tools import ToolError, preflight_submit
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


def test_create_leave_type_rejects_case_insensitive_duplicate(db, manager_context):
    svc = LeaveService(db)
    _create_leave_type(svc, manager_context, name="Annual Leave")
    with pytest.raises(ValueError, match="already exists"):
        _create_leave_type(svc, manager_context, name="annual leave")


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


def test_request_leave_rejects_past_dates(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context)
    with pytest.raises(ValueError, match="past"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 1, 1),
            end_date=date(2026, 1, 2),
            reason=None,
        )


def test_request_leave_rejects_overlap_diff_type(db, manager_context, employee_context):
    svc = LeaveService(db)
    annual = _create_leave_type(svc, manager_context, name="Annual Leave")
    sick = _create_leave_type(svc, manager_context, name="Sick Leave", default_days=Decimal(10))
    svc.request_leave(
        employee_context,
        leave_type_id=annual.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason=None,
    )
    with pytest.raises(ValueError, match="overlap"):
        svc.request_leave(
            employee_context,
            leave_type_id=sick.leave_type_id,
            start_date=date(2026, 9, 3),
            end_date=date(2026, 9, 5),  # shares the 2026-09-03 boundary
            reason=None,
        )


def test_request_leave_rejects_overlap_same_type(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        reason=None,
    )
    with pytest.raises(ValueError, match="overlap"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 4),  # inside the first request
            end_date=date(2026, 9, 7),
            reason=None,
        )


def test_request_leave_rejects_consecutive_run_over_cap(db, manager_context, employee_context):
    """3 days + back-to-back 3 days must trip the 3-day max-consecutive cap."""
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, max_consecutive_days=3, default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),  # 3 days, exactly at the cap — allowed
        reason=None,
    )
    with pytest.raises(ValueError, match="consecutive"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=date(2026, 9, 4),
            end_date=date(2026, 9, 6),  # makes a 6-day run
            reason=None,
        )


def test_preflight_submit_rejects_overlapping_existing_request(db, manager_context, employee_context):
    """The agent's stage-time preflight must catch a date the employee has
    already applied for (same day twice for one date)."""
    svc = LeaveService(db)
    annual = _create_leave_type(svc, manager_context, name="Annual Leave", default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=annual.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 5),
        reason=None,
    )
    with pytest.raises(ToolError, match="overlap"):
        preflight_submit(
            svc,
            employee_context,
            leave_type_name="Annual Leave",
            start_date=date(2026, 9, 4),  # inside the existing request
            end_date=date(2026, 9, 6),
        )


def test_preflight_submit_rejects_consecutive_run_over_cap(db, manager_context, employee_context):
    """Back-to-back same-type requests must trip the cap at stage time too."""
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, max_consecutive_days=3, default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason=None,
    )
    with pytest.raises(ToolError, match="consecutive"):
        preflight_submit(
            svc,
            employee_context,
            leave_type_name="Annual Leave",
            start_date=date(2026, 9, 4),  # makes a 6-day run
            end_date=date(2026, 9, 6),
        )


def test_preflight_submit_allows_dates_clear_of_existing_requests(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, max_consecutive_days=3, default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason=None,
    )
    preflight_submit(
        svc,
        employee_context,
        leave_type_name="Annual Leave",
        start_date=date(2026, 9, 7),  # gap breaks the run
        end_date=date(2026, 9, 9),
    )


def test_request_leave_allows_gap_between_requests(db, manager_context, employee_context):
    """A 1+ day gap breaks the run: 3 + 3 with a rest day must stay allowed."""
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, max_consecutive_days=3, default_days=Decimal(20))
    svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        reason=None,
    )
    second = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=date(2026, 9, 5),  # 2026-09-04 off — gap breaks the run
        end_date=date(2026, 9, 7),
        reason=None,
    )
    assert second.status == "PENDING"


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


def test_calculate_working_days_weekend_exclusion(db):
    svc = LeaveService(db)
    # 2026-08-21 is Friday, 2026-08-24 is Monday
    fri = date(2026, 8, 21)
    mon = date(2026, 8, 24)
    working_days, holidays = svc.calculate_working_days(fri, mon)
    # Friday and Monday are 2 working days (Sat & Sun excluded)
    assert working_days == Decimal("2.0")
    assert len(holidays) == 0


def test_calculate_working_days_with_company_holidays(db, manager_context):
    svc = LeaveService(db)
    # Create holiday on Monday 2026-08-24
    svc.create_company_holiday(
        manager_context,
        name="Test Monday Holiday",
        holiday_date=date(2026, 8, 24),
    )

    fri = date(2026, 8, 21)
    mon = date(2026, 8, 24)
    working_days, holidays = svc.calculate_working_days(fri, mon)
    # Friday is the only working day (Sat, Sun, and Mon holiday excluded)
    assert working_days == Decimal("1.0")
    assert len(holidays) == 1
    assert holidays[0].name == "Test Monday Holiday"


def test_calculate_working_days_yearly_recurring_holiday(db, manager_context):
    svc = LeaveService(db)
    # Recurring yearly on Nov 15
    svc.create_company_holiday(
        manager_context,
        name="Annual Foundation Day",
        holiday_date=date(2020, 11, 15),
        is_recurring_yearly=True,
    )

    # 2026-11-13 is Friday, 2026-11-15 is Sunday, 2026-11-16 is Monday
    # 2026-11-15 is a Sunday holiday
    working_days, holidays = svc.calculate_working_days(date(2026, 11, 13), date(2026, 11, 16))
    assert working_days == Decimal("2.0")  # Friday and Monday

    # In 2027, Nov 15 is Monday
    working_days_2027, holidays_2027 = svc.calculate_working_days(date(2027, 11, 12), date(2027, 11, 16))
    # Friday 12 (1), Sat 13 (0), Sun 14 (0), Mon 15 (holiday 0), Tue 16 (1) -> 2 working days
    assert working_days_2027 == Decimal("2.0")
    assert len(holidays_2027) == 1


def test_calculate_working_days_half_day(db):
    svc = LeaveService(db)
    # 2026-08-25 is Tuesday
    tue = date(2026, 8, 25)
    working_days, holidays = svc.calculate_working_days(tue, tue, is_half_day=True, half_day_period="MORNING")
    assert working_days == Decimal("0.5")

    # Half day on Saturday raises ValueError
    sat = date(2026, 8, 22)
    with pytest.raises(ValueError, match="weekend"):
        svc.calculate_working_days(sat, sat, is_half_day=True, half_day_period="AFTERNOON")


def test_half_day_leave_request_flow(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(10))

    tue = date(2026, 9, 8)  # Tuesday
    request = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=tue,
        end_date=tue,
        is_half_day=True,
        half_day_period="MORNING",
        reason="Doctor appointment",
    )
    assert request.is_half_day is True
    assert request.half_day_period == "MORNING"
    assert request.total_days == Decimal("0.5")

    # Approve and verify balance deduction
    svc.decide_request(manager_context, request.leave_request_id, approve=True)
    rows = svc.list_my_balance(employee_context, year=2026)
    row = next(r for r in rows if r["leave_type"].leave_type_id == leave_type.leave_type_id)
    assert row["used_days"] == Decimal("0.5")
    assert row["remaining_days"] == Decimal("9.5")


def test_half_day_non_colliding_morning_and_afternoon(db, manager_context, employee_context):
    svc = LeaveService(db)
    leave_type = _create_leave_type(svc, manager_context, default_days=Decimal(10))

    wed = date(2026, 9, 9)
    # Morning request
    req1 = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=wed,
        end_date=wed,
        is_half_day=True,
        half_day_period="MORNING",
    )
    assert req1.status == "PENDING"

    # Afternoon request on same day -> allowed!
    req2 = svc.request_leave(
        employee_context,
        leave_type_id=leave_type.leave_type_id,
        start_date=wed,
        end_date=wed,
        is_half_day=True,
        half_day_period="AFTERNOON",
    )
    assert req2.status == "PENDING"

    # Duplicate morning request on same day -> blocked!
    with pytest.raises(ValueError, match="overlap"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=wed,
            end_date=wed,
            is_half_day=True,
            half_day_period="MORNING",
        )

    # Full-day request on same day -> blocked!
    with pytest.raises(ValueError, match="overlap"):
        svc.request_leave(
            employee_context,
            leave_type_id=leave_type.leave_type_id,
            start_date=wed,
            end_date=wed,
            is_half_day=False,
        )


def test_company_holiday_and_team_calendar_http(
    db, client, manager_context, employee_context, employee_password, manager_password
):
    # 1. Login as manager and create a holiday
    mgr_login = client.post(
        "/api/auth/login",
        json={"email": manager_context.email, "password": manager_password},
    )
    mgr_token = mgr_login.json()["access_token"]

    holiday_res = client.post(
        "/api/leave/holidays",
        headers={"Authorization": f"Bearer {mgr_token}"},
        json={
            "name": "Spring Gala Day",
            "holiday_date": "2026-04-10",
            "description": "Annual company celebration closure.",
            "is_recurring_yearly": True,
        },
    )
    assert holiday_res.status_code == 201
    holiday_id = holiday_res.json()["holiday_id"]

    # 2. Login as employee and list holidays
    emp_login = client.post(
        "/api/auth/login",
        json={"email": employee_context.email, "password": employee_password},
    )
    emp_token = emp_login.json()["access_token"]

    holidays_list = client.get("/api/leave/holidays", headers={"Authorization": f"Bearer {emp_token}"})
    assert holidays_list.status_code == 200
    assert any(h["holiday_id"] == holiday_id for h in holidays_list.json())

    # 3. Test calculate-days preview endpoint
    calc_res = client.post(
        "/api/leave/calculate-days",
        headers={"Authorization": f"Bearer {emp_token}"},
        json={
            "start_date": "2026-04-09",
            "end_date": "2026-04-13",
        },
    )
    assert calc_res.status_code == 200
    calc_data = calc_res.json()
    # 2026-04-09 (Thu), 2026-04-10 (Fri holiday), 2026-04-11 (Sat), 2026-04-12 (Sun), 2026-04-13 (Mon)
    # Total calendar days = 5, weekend days = 2, holiday days = 1, total working days = 2 (Thu + Mon)
    assert Decimal(calc_data["total_working_days"]) == Decimal("2")
    assert calc_data["calendar_days"] == 5
    assert calc_data["weekend_days"] == 2
    assert calc_data["holiday_days"] == 1

    # 4. Test team out of office endpoint
    team_res = client.get("/api/leave/team-out-of-office", headers={"Authorization": f"Bearer {emp_token}"})
    assert team_res.status_code == 200
    assert isinstance(team_res.json(), list)

    # 5. Manager deletes holiday
    del_res = client.delete(
        f"/api/leave/holidays/{holiday_id}",
        headers={"Authorization": f"Bearer {mgr_token}"},
    )
    assert del_res.status_code == 200

