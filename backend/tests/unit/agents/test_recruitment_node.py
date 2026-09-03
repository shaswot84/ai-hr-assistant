"""Unit tests for the recruitment agent and node.

Tests the capabilities:
1. View Open Vacancies (with vacancies_list widget)
2. Apply for Vacancies (with apply_vacancy resume upload widget)
3. Check Application Status (with applications_list widget)
4. Role gating and manager views
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app.agents.recruitment_agent.node import make_recruitment_node
from app.contracts.auth import UserContext


class _Vacancy:
    def __init__(
        self,
        title: str,
        *,
        employment_type: str = "FULL_TIME",
        closing_date=None,
        description: str | None = None,
        status: str = "OPEN",
        department_name: str | None = None,
    ) -> None:
        self.title = title
        self.employment_type = employment_type
        self.closing_date = closing_date
        self.description = description
        self.status = status
        self.department_name = department_name
        self.department = type("D", (), {"name": department_name})() if department_name else None
        self.vacancy_id = uuid.uuid4()


class _Application:
    def __init__(self, vacancy: _Vacancy, *, status: str = "APPLIED") -> None:
        self.application_id = uuid.uuid4()
        self.vacancy = vacancy
        self.vacancy_id = vacancy.vacancy_id
        self.application_status = status
        self.applied_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class FakeRecruitmentService:
    """A RecruitmentService stub for the node."""

    def __init__(self, vacancies=None, applications=None) -> None:
        self.vacancies = vacancies or []
        self.applications = applications or []

    async def list_vacancies(self, actor=None):
        if actor is None or actor.coarse_role == "CANDIDATE":
            return [v for v in self.vacancies if v.status == "OPEN"]
        return self.vacancies

    async def list_all_applications(self, actor):
        return self.applications

    async def list_vacancy_applications(self, actor, vacancy_id):
        return [a for a in self.applications if a.vacancy.vacancy_id == vacancy_id]

    async def list_my_applications(self, actor):
        return self.applications

    async def withdraw_application(self, actor, application_id):
        if actor is None or actor.coarse_role != "CANDIDATE":
            raise PermissionError("Only candidates can withdraw their applications.")
        app = next((a for a in self.applications if a.application_id == application_id), None)
        if app is None:
            raise ValueError("Application not found.")
        app.application_status = "WITHDRAWN"
        return app


def _candidate() -> UserContext:
    return UserContext(subject="cand-1", email="c@x.com", display_name="C", coarse_role="CANDIDATE")


def _hr() -> UserContext:
    return UserContext(subject="mgr-1", email="m@x.com", display_name="M", coarse_role="HR_ADMIN")


def _seeded() -> tuple[list[_Vacancy], list[_Application]]:
    analyst = _Vacancy(
        "Data Analyst",
        description="Turn raw data into decisions with SQL and Python.",
        closing_date=datetime(2026, 9, 1, tzinfo=UTC).date(),
    )
    backend = _Vacancy("Senior Backend Engineer", status="CLOSED")
    return [analyst, backend], [_Application(analyst, status="SHORTLISTED")]


async def _run(actor, service, query: str) -> tuple[dict, list[dict]]:
    events: list[dict] = []
    node = make_recruitment_node(actor=actor, service=service)
    state = await node({"current_query": query, "messages": []}, events.append)
    assert any(e["type"] == "message" for e in events)
    return state, events


@pytest.mark.asyncio
async def test_lists_open_vacancies_only():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(None, service, "what jobs are open")

    assert state["agent"] == "recruitment"
    assert "Data Analyst" in state["answer"]
    assert "Senior Backend Engineer" not in state["answer"]  # CLOSED is hidden
    assert "FULL_TIME" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancies_list"
    assert len(state["ui_widget"]["vacancies"]) == 1


@pytest.mark.asyncio
async def test_vacancy_detail_by_title():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(None, service, "tell me about the data analyst vacancy")

    assert "Turn raw data into decisions with SQL and Python." in state["answer"]
    assert "Data Analyst" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "apply_vacancy"
    assert state["ui_widget"]["vacancy_title"] == "Data Analyst"


@pytest.mark.asyncio
async def test_apply_with_matched_vacancy_renders_upload_widget():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(_candidate(), service, "how do i apply for the data analyst job")

    assert "Data Analyst" in state["answer"]
    assert "upload your resume" in state["answer"].lower()
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "apply_vacancy"
    assert state["ui_widget"]["vacancy_title"] == "Data Analyst"


@pytest.mark.asyncio
async def test_apply_generic_lists_open_vacancies():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(_candidate(), service, "i want to apply")

    assert "Data Analyst" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancies_list"


@pytest.mark.asyncio
async def test_my_applications_for_candidate():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state, events = await _run(_candidate(), service, "show my applications")

    assert "Data Analyst" in state["answer"]
    assert "SHORTLISTED" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "applications_list"
    assert len(state["ui_widget"]["applications"]) == 1


@pytest.mark.asyncio
async def test_check_application_status_query():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state, events = await _run(_candidate(), service, "what is the status of my application?")

    assert "Data Analyst" in state["answer"]
    assert "SHORTLISTED" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "applications_list"


@pytest.mark.asyncio
async def test_my_applications_gate_for_non_candidate():
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(employee, service, "show my applications")

    assert "Only candidates can view their applications" in state["answer"]
    assert state["ui_widget"] is None


@pytest.mark.asyncio
async def test_hr_lists_all_applications():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state, events = await _run(_hr(), service, "show me candidate applications to review")

    assert "Data Analyst" in state["answer"]
    assert "SHORTLISTED" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "applications_list"


@pytest.mark.asyncio
async def test_hr_decision_guidance():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state, events = await _run(_hr(), service, "approve the data analyst application")

    assert "manager portal" in state["answer"].lower()
    assert state["ui_widget"] is not None


@pytest.mark.asyncio
async def test_help_reply_lists_capabilities():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(None, service, "hello")

    assert "Recruitment" in state["answer"]
    assert "Data Analyst" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancies_list"


@pytest.mark.asyncio
async def test_node_state_shape():
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(None, service, "what jobs are open")

    assert state["agent"] == "recruitment"
    assert state["messages"][-1].content == state["answer"]
    assert state["citations"] == []
    assert state["knowledge_result"] is None
    assert state["confidence"] == 0.0
    assert state["safety"] == "PASS"
    assert state["ui_widget"] is not None


@pytest.mark.asyncio
async def test_candidate_withdraw_application():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state, events = await _run(_candidate(), service, "withdraw my application for data analyst")

    assert "withdrawn" in state["answer"].lower()
    assert "Data Analyst" in state["answer"]
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "applications_list"
    assert apps[0].application_status == "WITHDRAWN"


@pytest.mark.asyncio
async def test_candidate_withdraw_no_active_applications():
    vacancies, _ = _seeded()
    service = FakeRecruitmentService(vacancies, [])
    state, events = await _run(_candidate(), service, "withdraw my application")

    assert "don't have any active applications" in state["answer"].lower()


@pytest.mark.asyncio
async def test_non_candidate_withdraw_blocked():
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(employee, service, "withdraw my application")

    assert "Only candidates" in state["answer"]


@pytest.mark.asyncio
async def test_employee_views_open_vacancies_receives_can_apply_false():
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(employee, service, "what jobs are open")

    assert state["agent"] == "recruitment"
    assert "Data Analyst" in state["answer"]
    assert "internal transfer" in state["answer"].lower()
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancies_list"
    assert state["ui_widget"]["can_apply"] is False
    assert state["ui_widget"]["vacancies"][0]["can_apply"] is False


@pytest.mark.asyncio
async def test_employee_views_vacancy_detail_receives_detail_widget_not_apply_widget():
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(employee, service, "tell me about the data analyst vacancy")

    assert "Data Analyst" in state["answer"]
    assert "upload your resume" not in state["answer"].lower()
    assert "internal transfer" in state["answer"].lower()
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancy_detail"
    assert state["ui_widget"]["can_apply"] is False
    assert state["ui_widget"]["vacancy"]["title"] == "Data Analyst"


@pytest.mark.asyncio
async def test_employee_asks_to_apply_receives_internal_transfer_guidance():
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state, events = await _run(employee, service, "i want to apply for the data analyst position")

    assert "Data Analyst" in state["answer"]
    assert "external candidates" in state["answer"].lower()
    assert "internal transfer" in state["answer"].lower()
    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "vacancy_detail"
    assert state["ui_widget"]["can_apply"] is False


@pytest.mark.asyncio
async def test_click_parentheses_vacancy_title_with_closed_and_open_roles():
    closed_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="CLOSED",
        department_name="Engineer",
        description="Maintain infrastructure reliability.",
    )
    open_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="OPEN",
        department_name="Engineering",
        description="Scale global infrastructure and reliability.",
    )
    service = FakeRecruitmentService([closed_role, open_role])
    state, events = await _run(None, service, "Tell me about the SITE RELIABILITY ENGINEER (SRE) vacancy")

    assert state["agent"] == "recruitment"
    assert "SITE RELIABILITY ENGINEER (SRE)" in state["answer"]
    assert state["ui_widget"] is not None
    # For visitors/candidates, it should return apply_vacancy widget for the OPEN role, not loop back to vacancies_list
    assert state["ui_widget"]["type"] == "apply_vacancy"
    assert state["ui_widget"]["vacancy_title"] == "SITE RELIABILITY ENGINEER (SRE)"
    assert state["ui_widget"]["vacancy_id"] == str(open_role.vacancy_id)


@pytest.mark.asyncio
async def test_apply_parentheses_vacancy_in_chat():
    closed_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="CLOSED",
        department_name="Engineer",
    )
    open_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="OPEN",
        department_name="Engineering",
    )
    service = FakeRecruitmentService([closed_role, open_role])
    state, events = await _run(_candidate(), service, "I want to apply for SITE RELIABILITY ENGINEER (SRE)")

    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "apply_vacancy"
    assert state["ui_widget"]["vacancy_id"] == str(open_role.vacancy_id)
    assert "upload your resume" in state["answer"].lower()


@pytest.mark.asyncio
async def test_click_acronym_sre():
    open_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="OPEN",
        department_name="Engineering",
    )
    service = FakeRecruitmentService([open_role])
    state, events = await _run(None, service, "Tell me about the SRE vacancy")

    assert state["ui_widget"] is not None
    assert state["ui_widget"]["type"] == "apply_vacancy"
    assert state["ui_widget"]["vacancy_title"] == "SITE RELIABILITY ENGINEER (SRE)"


@pytest.mark.asyncio
async def test_manager_department_disambiguation_for_duplicate_titles():
    closed_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="CLOSED",
        department_name="Engineer",
    )
    open_role = _Vacancy(
        "SITE RELIABILITY ENGINEER (SRE)",
        status="OPEN",
        department_name="Engineering",
    )
    app_closed = _Application(closed_role, status="APPLIED")
    app_open = _Application(open_role, status="APPLIED")
    service = FakeRecruitmentService([closed_role, open_role], [app_closed, app_open])

    # Manager queries about closed role in Engineer
    state, events = await _run(
        _hr(), service, "Who applied for the closed SITE RELIABILITY ENGINEER (SRE) role in Engineer?"
    )
    assert "SITE RELIABILITY ENGINEER (SRE)" in state["answer"]

