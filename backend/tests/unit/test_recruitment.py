from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.domain.identity import ApplicationUser, Candidate, Person
from app.domain.outbox import OutboxJob
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


def test_apply_enqueues_candidate_confirmation_and_manager_alert(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf")

    jobs = db.scalars(
        select(OutboxJob).where(OutboxJob.aggregate_id == application.application_id)
    ).all()
    by_type = {j.job_type: j for j in jobs}

    assert "SEND_APPLICATION_RECEIVED" in by_type
    assert by_type["SEND_APPLICATION_RECEIVED"].payload["to_email"] == candidate_context.email

    assert "SEND_NEW_APPLICATION_ALERT" in by_type
    assert by_type["SEND_NEW_APPLICATION_ALERT"].payload["to_email"] == manager_context.email


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


def test_list_all_applications_spans_every_vacancy(db, manager_context, candidate_context):
    svc = RecruitmentService(db)
    vacancy_a = _create_vacancy(svc, manager_context)
    vacancy_b = svc.create_vacancy(
        manager_context,
        title="Product Designer",
        department_name="Design",
        description="Own product design end to end.",
        employment_type="full_time",
        opening_date=None,
        closing_date=None,
    )
    app_a = svc.apply(candidate_context, vacancy_id=vacancy_a.vacancy_id, cv_object_key="resumes/a.pdf")
    app_b = svc.apply(candidate_context, vacancy_id=vacancy_b.vacancy_id, cv_object_key="resumes/b.pdf")

    all_apps = {a.application_id for a in svc.list_all_applications(manager_context)}
    assert app_a.application_id in all_apps
    assert app_b.application_id in all_apps


def test_list_all_applications_requires_hr_admin(db, candidate_context):
    svc = RecruitmentService(db)
    with pytest.raises(PermissionError_):
        svc.list_all_applications(candidate_context)


def _seed_evaluation(db, application_id):
    """Attach an AI screening result (LLM-shaped raw_payload) to an application."""
    db.add(
        ApplicationEvaluation(
            application_id=application_id,
            score=76,
            overview="Strong match.",
            raw_payload={
                "matchScore": 76,
                "recommendation": "Good Match",
                "summary": "Strong match.",
                "scoreFactors": [
                    {"factor": "Skills Match", "score": 80, "note": "Has most required skills."},
                ],
                "strengths": ["Strong Python background"],
                "weaknesses": ["No Kubernetes experience mentioned"],
                "matchedKeywords": ["python", "fastapi"],
                "missingKeywords": ["kubernetes"],
            },
            model="test-model",
            prompt_version="v1",
            evaluated_at=datetime.now(UTC),
        )
    )
    db.commit()


def test_apply_as_new_candidate_provisions_account_and_login(db, client, manager_context):
    """First-time candidates self-register: account + application in one transaction, then can log in."""
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)

    application = svc.apply_as_new_candidate(
        vacancy_id=vacancy.vacancy_id,
        cv_object_key="resumes/c.pdf",
        first_name="New",
        last_name="Candidate",
        email="Newbie@Acme-Hr-Test.Dev",
        phone="+91 90000 00000",
        password="password-123",
    )
    assert application.application_status == "APPLIED"

    # Person + CANDIDATE account + Candidate rows were provisioned (email normalized).
    person = db.scalar(select(Person).where(Person.email == "newbie@acme-hr-test.dev"))
    assert person is not None
    app_user = db.scalar(
        select(ApplicationUser).where(ApplicationUser.person_id == person.person_id)
    )
    assert app_user.coarse_role == "CANDIDATE"
    candidate = db.scalar(select(Candidate).where(Candidate.person_id == person.person_id))
    assert candidate is not None

    # The password chosen in the form works against the login endpoint.
    login = client.post(
        "/api/auth/login",
        json={"email": "newbie@acme-hr-test.dev", "password": "password-123"},
    )
    assert login.status_code == 200


def test_apply_as_new_candidate_blocks_existing_email(db, manager_context, candidate_context):
    """A duplicate email is blocked with a sign-in prompt instead of a second account."""
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    with pytest.raises(ValueError, match="already exists"):
        svc.apply_as_new_candidate(
            vacancy_id=vacancy.vacancy_id,
            cv_object_key="resumes/c.pdf",
            first_name="Alex",
            last_name="Applicant",
            email=candidate_context.email,
            phone=None,
            password="password-123",
        )


def test_apply_as_new_candidate_requires_open_vacancy(db, manager_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    svc.archive_vacancy(manager_context, vacancy.vacancy_id)
    with pytest.raises(ValueError, match="not open"):
        svc.apply_as_new_candidate(
            vacancy_id=vacancy.vacancy_id,
            cv_object_key="resumes/c.pdf",
            first_name="New",
            last_name="Candidate",
            email="newbie2@acme-hr-test.dev",
            phone=None,
            password="password-123",
        )


def test_apply_as_new_candidate_requires_password_length(db, manager_context):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    with pytest.raises(ValueError, match="at least 8"):
        svc.apply_as_new_candidate(
            vacancy_id=vacancy.vacancy_id,
            cv_object_key="resumes/c.pdf",
            first_name="New",
            last_name="Candidate",
            email="newbie3@acme-hr-test.dev",
            phone=None,
            password="short",
        )


def test_public_vacancy_listing_shows_only_open(db, client, manager_context):
    """Anonymous visitors can browse open vacancies without signing in."""
    svc = RecruitmentService(db)
    open_vacancy = _create_vacancy(svc, manager_context)
    closed_vacancy = _create_vacancy(svc, manager_context)
    svc.archive_vacancy(manager_context, closed_vacancy.vacancy_id)

    res = client.get("/api/vacancies")  # no Authorization header
    assert res.status_code == 200
    ids = {v["vacancy_id"] for v in res.json()}
    assert str(open_vacancy.vacancy_id) in ids
    assert str(closed_vacancy.vacancy_id) not in ids


def test_seed_candidate_apply_still_works_with_auth(db, manager_context, candidate_context):
    """The authenticated apply flow is unchanged alongside the public one."""
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    assert application.application_status == "APPLIED"


def test_manager_application_detail_serializes_screening_as_snake_case(
    db, client, manager_context, candidate_context, manager_password
):
    """Regression test: the LLM's raw evaluation payload uses camelCase keys
    (`matchedKeywords`, `scoreFactors`, ...), but every other field in this
    API is snake_case on the wire. A schema that round-tripped those
    camelCase keys straight through to the HTTP response (via a Pydantic
    alias generator) previously broke the frontend, which reads
    `matched_keywords` — this crashed the application detail pages with
    "Cannot read properties of undefined (reading 'map')". Assert the
    manager-facing JSON body uses snake_case throughout.
    """
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    _seed_evaluation(db, application.application_id)

    login = client.post(
        "/api/auth/login",
        json={"email": manager_context.email, "password": manager_password},
    )
    token = login.json()["access_token"]
    res = client.get(
        f"/api/applications/{application.application_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert res.status_code == 200
    detail = res.json()["evaluation"]["detail"]
    assert detail["matched_keywords"] == ["python", "fastapi"]
    assert detail["missing_keywords"] == ["kubernetes"]
    assert detail["match_score"] == 76
    assert detail["score_factors"][0]["factor"] == "Skills Match"
    assert "matchedKeywords" not in detail


def test_candidate_application_view_excludes_screening_result(
    db, client, manager_context, candidate_context, candidate_password
):
    """Candidates must only ever see their application status, never the AI
    screening result (score, strengths/weaknesses) a manager uses to decide.
    """
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )
    _seed_evaluation(db, application.application_id)

    login = client.post(
        "/api/auth/login",
        json={"email": candidate_context.email, "password": candidate_password},
    )
    token = login.json()["access_token"]

    detail_res = client.get(
        f"/api/applications/mine/{application.application_id}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert detail_res.status_code == 200
    body = detail_res.json()
    assert body["application_status"] == "APPLIED"
    assert "evaluation" not in body
    assert "evaluated" not in body

    list_res = client.get(
        "/api/applications/mine", headers={"Authorization": f"Bearer {token}"}
    )
    assert list_res.status_code == 200
    assert all("evaluation" not in a for a in list_res.json())


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


def test_all_applications_http_endpoint(
    db, client, manager_context, candidate_context, manager_password
):
    svc = RecruitmentService(db)
    vacancy = _create_vacancy(svc, manager_context)
    application = svc.apply(
        candidate_context, vacancy_id=vacancy.vacancy_id, cv_object_key="resumes/a.pdf"
    )

    login = client.post(
        "/api/auth/login",
        json={"email": manager_context.email, "password": manager_password},
    )
    token = login.json()["access_token"]
    res = client.get("/api/applications", headers={"Authorization": f"Bearer {token}"})
    assert res.status_code == 200
    ids = {a["application_id"] for a in res.json()}
    assert str(application.application_id) in ids
