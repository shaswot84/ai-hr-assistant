from __future__ import annotations

from datetime import UTC, datetime

import pytest

from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.domain.recruitment import ApplicationEvaluation


def _create_vacancy(svc, actor):
    return svc.create_vacancy(
        actor,
        title="Senior Backend Engineer",
        department_name="Engineering",
        description="Build scalable APIs.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
    )


def test_create_vacancy_requires_hr_admin(db, candidate_context):
    svc = RecruitmentService(db)
    with pytest.raises(PermissionError_):
        _create_vacancy(svc, candidate_context)


def test_create_vacancy_success(db, manager_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    assert vacancy.status == "OPEN"
    assert vacancy.employment_type == "FULL_TIME"
    assert vacancy in svc.list_vacancies(manager_context)


def test_candidate_can_apply_once_then_second_apply_fails(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)

    application = svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf")
    assert application.application_status == "APPLIED"

    with pytest.raises(ValueError, match="already applied"):
        svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/b.pdf")


def test_apply_requires_open_vacancy(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    svc.archive_vacancy(manager_context, vacancy.vacancy_id)

    with pytest.raises(ValueError, match="not open"):
        svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf")


def test_decide_application_shortlist_then_redecide_is_blocked(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf")

    decided = svc.decide_application(manager_context, application.application_id, approve=True)
    assert decided.application_status == "SHORTLISTED"

    # Regression test: previously a manager could re-decide an already
    # SHORTLISTED/REJECTED application, re-sending the candidate email and
    # (on REJECTED -> SHORTLISTED) leaving a stale rejected_at behind.
    with pytest.raises(ValueError, match="already been decided"):
        svc.decide_application(manager_context, application.application_id, approve=False)


def test_decide_application_reject_sets_rejected_at(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf")

    decided = svc.decide_application(manager_context, application.application_id, approve=False)
    assert decided.application_status == "REJECTED"
    assert decided.rejected_at is not None


def test_archive_and_reopen_vacancy(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)

    closed = svc.archive_vacancy(manager_context, vacancy.vacancy_id)
    assert closed.status == "CLOSED"
    # Candidates only see OPEN vacancies; managers still see everything.
    assert closed.vacancy_id not in {v.vacancy_id for v in svc.list_vacancies(candidate_context)}
    assert closed.vacancy_id in {v.vacancy_id for v in svc.list_vacancies(manager_context)}

    reopened = svc.reopen_vacancy(manager_context, vacancy.vacancy_id)
    assert reopened.status == "OPEN"
    assert reopened.vacancy_id in {v.vacancy_id for v in svc.list_vacancies(candidate_context)}


def test_application_detail_serializes_job_match_as_snake_case(
    db, client, manager_context, candidate_context, candidate_password
):
    """Regression test: the LLM's raw evaluation payload uses camelCase keys
    (`jobMatch.matchedKeywords`), but every other field in this API is
    snake_case on the wire. A `JobMatch` schema that round-tripped those
    camelCase keys straight through to the HTTP response (via a Pydantic
    alias generator) silently broke the frontend, which reads
    `job_match.matched_keywords` — this crashed the candidate/manager
    application detail pages with "Cannot read properties of undefined
    (reading 'map')". Assert the actual JSON body uses snake_case.
    """
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    db.add(
        ApplicationEvaluation(
            application_id=application.application_id,
            score=76,
            overview="Strong match.",
            raw_payload={
                "overallScore": 76,
                "scoreJustification": "Solid alignment with the role.",
                "clarity": {"summary": "Clear.", "issues": []},
                "impact": {"summary": "", "issues": []},
                "formatting": {"summary": "", "issues": []},
                "missingSections": [],
                "improvedBullets": [],
                "jobMatch": {
                    "matchScore": 76,
                    "summary": "Strong match.",
                    "matchedKeywords": ["python", "fastapi"],
                    "missingKeywords": ["kubernetes"],
                },
            },
            model="test-model",
            prompt_version="v1",
            evaluated_at=datetime.now(UTC),
        )
    )
    db.commit()

    login = client.post(
        "/api/auth/login",
        json={"email": candidate_context.email, "password": candidate_password},
    )
    token = login.json()["access_token"]
    res = client.get(
        f"/api/applications/mine/{application.application_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    job_match = res.json()["evaluation"]["detail"]["job_match"]
    assert job_match["matched_keywords"] == ["python", "fastapi"]
    assert job_match["missing_keywords"] == ["kubernetes"]
    assert job_match["match_score"] == 76
    assert "matchedKeywords" not in job_match


def test_create_vacancy_http_requires_hr_admin(client, candidate_context, candidate_password):
    login = client.post(
        "/api/auth/login",
        json={"email": candidate_context.email, "password": candidate_password},
    )
    token = login.json()["access_token"]
    res = client.post(
        "/api/vacancies",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "title": "Should Not Be Created",
            "department_name": "Engineering",
            "employment_type": "full_time",
        },
    )
    assert res.status_code == 403
