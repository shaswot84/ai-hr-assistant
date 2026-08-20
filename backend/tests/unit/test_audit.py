from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.domain.identity import ApplicationUser
from app.repositories.audit import AuditRepo


def _login(client, email: str, password: str) -> str:
    res = client.post("/api/auth/login", json={"email": email, "password": password})
    return res.json()["access_token"]


def test_audit_repo_record_and_list(db, manager_context):
    app_user = db.query(ApplicationUser).filter_by(external_subject=manager_context.subject).first()
    repo = AuditRepo(db)

    # Record 3 events
    target_id_1 = uuid.uuid4()
    entry1 = repo.record(
        actor_user_id=app_user.user_id,
        action="VACANCY_CREATED",
        target_type="Vacancy",
        target_id=target_id_1,
        authorization_result="ALLOW",
        new_state={"title": "Software Engineer", "status": "OPEN"},
    )

    target_id_2 = uuid.uuid4()
    entry2 = repo.record(
        actor_user_id=app_user.user_id,
        action="EMPLOYEE_CREATED",
        target_type="Employee",
        target_id=target_id_2,
        authorization_result="ALLOW",
        new_state={"name": "Alice Developer"},
    )

    entry3 = repo.record(
        actor_user_id=None,
        action="SYSTEM_MAINTENANCE",
        target_type="System",
        target_id=None,
        authorization_result="ALLOW",
        previous_state={"maintenance": False},
        new_state={"maintenance": True},
    )
    db.commit()

    # Query all
    items, total = repo.list_logs()
    assert total == 3
    assert len(items) == 3
    assert items[0].audit_id == entry3.audit_id
    assert items[0].actor_name is None
    assert items[1].audit_id == entry2.audit_id
    assert items[1].actor_name == "Hiring Manager"
    assert items[1].actor_role == "HR_ADMIN"
    assert items[1].actor_email == "manager@acme-hr-test.dev"

    # Filter by action
    items_action, total_action = repo.list_logs(action="VACANCY_CREATED")
    assert total_action == 1
    assert items_action[0].audit_id == entry1.audit_id
    assert items_action[0].new_state == {"title": "Software Engineer", "status": "OPEN"}

    # Filter by target_type (case-insensitive)
    items_target, total_target = repo.list_logs(target_type="employee")
    assert total_target == 1
    assert items_target[0].audit_id == entry2.audit_id

    # Filter by actor_user_id
    items_actor, total_actor = repo.list_logs(actor_user_id=app_user.user_id)
    assert total_actor == 2

    # Search by text
    items_search, total_search = repo.list_logs(search="Software")
    assert total_search == 1
    assert items_search[0].audit_id == entry1.audit_id

    # Search by actor name
    items_search_actor, total_search_actor = repo.list_logs(search="Hiring")
    assert total_search_actor == 2

    # Get by ID
    single = repo.get_by_id(entry1.audit_id)
    assert single is not None
    assert single.action == "VACANCY_CREATED"
    assert single.actor_name == "Hiring Manager"

    # Get filter options
    opts = repo.get_filter_options()
    assert "VACANCY_CREATED" in opts["actions"]
    assert "EMPLOYEE_CREATED" in opts["actions"]
    assert "SYSTEM_MAINTENANCE" in opts["actions"]
    assert opts["total_count"] == 3
    assert opts["today_count"] == 3
    assert opts["unique_actors_count"] == 1


def test_audit_logs_api_requires_hr_admin(
    client, manager_context, manager_password, candidate_context, candidate_password
):
    # Anonymous request -> 401
    res = client.get("/api/audit/logs")
    assert res.status_code == 401

    # Candidate request -> 403
    cand_token = _login(client, candidate_context.email, candidate_password)
    res_cand = client.get("/api/audit/logs", headers={"Authorization": f"Bearer {cand_token}"})
    assert res_cand.status_code == 403

    # HR_ADMIN request -> 200
    mgr_token = _login(client, manager_context.email, manager_password)
    res_mgr = client.get("/api/audit/logs", headers={"Authorization": f"Bearer {mgr_token}"})
    assert res_mgr.status_code == 200
    body = res_mgr.json()
    assert "items" in body
    assert "total" in body
    assert "page" in body
    assert "page_size" in body
    assert "total_pages" in body


def test_audit_api_filtering_and_detail(client, db, manager_context, manager_password):
    mgr_token = _login(client, manager_context.email, manager_password)
    headers = {"Authorization": f"Bearer {mgr_token}"}

    app_user = db.query(ApplicationUser).filter_by(external_subject=manager_context.subject).first()
    repo = AuditRepo(db)

    target_id = uuid.uuid4()
    entry = repo.record(
        actor_user_id=app_user.user_id,
        action="LEAVE_REQUESTED",
        target_type="LeaveRequest",
        target_id=target_id,
        authorization_result="ALLOW",
        previous_state=None,
        new_state={"days": 3, "reason": "Vacation"},
    )
    db.commit()

    # List with action filter
    res = client.get("/api/audit/logs?action=LEAVE_REQUESTED", headers=headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 1
    assert data["items"][0]["action"] == "LEAVE_REQUESTED"
    assert data["items"][0]["actor_name"] == "Hiring Manager"

    # Get single audit log
    res_detail = client.get(f"/api/audit/logs/{entry.audit_id}", headers=headers)
    assert res_detail.status_code == 200
    detail = res_detail.json()
    assert detail["audit_id"] == str(entry.audit_id)
    assert detail["action"] == "LEAVE_REQUESTED"
    assert detail["new_state"] == {"days": 3, "reason": "Vacation"}

    # Get non-existent audit log -> 404
    non_existent = uuid.uuid4()
    res_404 = client.get(f"/api/audit/logs/{non_existent}", headers=headers)
    assert res_404.status_code == 404

    # Get filter options
    res_filters = client.get("/api/audit/filters", headers=headers)
    assert res_filters.status_code == 200
    filters_data = res_filters.json()
    assert "LEAVE_REQUESTED" in filters_data["actions"]
    assert "LeaveRequest" in filters_data["target_types"]
    assert filters_data["total_count"] >= 1
