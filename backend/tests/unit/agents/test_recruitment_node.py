"""Unit tests for the deterministic recruitment node.

The node answers the read paths (open vacancies, vacancy detail, my
applications, manager application lists) from a fake RecruitmentService and
defers the write paths (apply / decisions) honestly to the portal.
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
    ) -> None:
        self.title = title
        self.employment_type = employment_type
        self.closing_date = closing_date
        self.description = description
        self.status = status
        self.vacancy_id = uuid.uuid4()


class _Application:
    def __init__(self, vacancy: _Vacancy, *, status: str = "APPLIED") -> None:
        self.vacancy = vacancy
        self.application_status = status
        self.applied_at = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)


class FakeRecruitmentService:
    """A RecruitmentService stub for the node's read paths."""

    def __init__(self, vacancies=None, applications=None) -> None:
        self.vacancies = vacancies or []
        self.applications = applications or []

    def list_vacancies(self, actor=None):
        if actor is None or actor.coarse_role == "CANDIDATE":
            return [v for v in self.vacancies if v.status == "OPEN"]
        return self.vacancies

    def list_all_applications(self, actor):
        return self.applications

    def list_vacancy_applications(self, actor, vacancy_id):
        return [a for a in self.applications if a.vacancy.vacancy_id == vacancy_id]

    def list_my_applications(self, actor):
        return self.applications


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


async def _run(actor, service, query: str) -> dict:
    events: list[dict] = []
    node = make_recruitment_node(actor=actor, service=service)
    state = await node({"current_query": query, "messages": []}, events.append)
    assert [e["type"] for e in events] == ["message"]
    return state


@pytest.mark.asyncio
async def test_lists_open_vacancies_only():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(None, service, "what jobs are open")

    assert state["agent"] == "recruitment"
    assert "Data Analyst" in state["answer"]
    assert "Senior Backend Engineer" not in state["answer"]  # CLOSED is hidden
    assert "FULL_TIME" in state["answer"]


@pytest.mark.asyncio
async def test_vacancy_detail_by_title():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(None, service, "tell me about the data analyst vacancy")

    assert "Turn raw data into decisions with SQL and Python." in state["answer"]
    assert "Data Analyst" in state["answer"]
    assert "Careers" in state["answer"]


@pytest.mark.asyncio
async def test_apply_defers_to_careers_with_matched_vacancy():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(_candidate(), service, "how do i apply for the data analyst job")

    assert "Data Analyst" in state["answer"]
    assert "Careers" in state["answer"]
    assert "resume upload" in state["answer"]


@pytest.mark.asyncio
async def test_apply_defers_and_lists_open_vacancies():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(_candidate(), service, "i want to apply")

    assert "Careers" in state["answer"]
    assert "Data Analyst" in state["answer"]  # open vacancy listed so the ask isn't a dead end


@pytest.mark.asyncio
async def test_my_applications_for_candidate():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state = await _run(_candidate(), service, "show my applications")

    assert state["answer"] == "Your applications:\n- Data Analyst — SHORTLISTED (applied 2026-08-01)"


@pytest.mark.asyncio
async def test_my_applications_gate_for_non_candidate():
    """An EMPLOYEE (not a candidate, not HR) asking about their applications
    gets the role gate — only candidates have applications. HR admins asking
    about applications get the manager view instead (see the HR branch)."""
    employee = UserContext(
        subject="emp-1", email="e@x.com", display_name="E", coarse_role="EMPLOYEE"
    )
    service = FakeRecruitmentService(*_seeded())
    state = await _run(employee, service, "show my applications")

    assert "Only candidates can view their applications" in state["answer"]


@pytest.mark.asyncio
async def test_hr_lists_all_applications():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state = await _run(_hr(), service, "show me all applications")

    assert "All applications:" in state["answer"]
    assert "Data Analyst — SHORTLISTED" in state["answer"]


@pytest.mark.asyncio
async def test_hr_lists_applications_for_named_vacancy():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state = await _run(_hr(), service, "who applied for the data analyst role")

    assert state["answer"] == "Applications for Data Analyst:\n- Data Analyst — SHORTLISTED (applied 2026-08-01)"


@pytest.mark.asyncio
async def test_hr_decision_defers_to_portal():
    vacancies, apps = _seeded()
    service = FakeRecruitmentService(vacancies, apps)
    state = await _run(_hr(), service, "approve the data analyst application")

    assert "manager portal" in state["answer"]
    assert "can't change an application's status" in state["answer"]
    assert "Applications for Data Analyst:" in state["answer"]


@pytest.mark.asyncio
async def test_help_reply_lists_capabilities():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(None, service, "hello")

    assert "Recruitment" in state["answer"]
    assert "Careers" in state["answer"]
    assert "Data Analyst" in state["answer"]


@pytest.mark.asyncio
async def test_node_state_shape():
    service = FakeRecruitmentService(*_seeded())
    state = await _run(None, service, "what jobs are open")

    assert state["agent"] == "recruitment"
    assert state["messages"][-1].content == state["answer"]
    assert state["citations"] == []
    assert state["knowledge_result"] is None
    assert state["confidence"] == 0.0
    assert state["safety"] == "PASS"
