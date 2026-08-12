from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError

from app.api.deps import get_optional_user, require_role
from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.contracts.auth import UserContext
from app.db.sync_session import get_db
from app.domain.identity import Department, Person
from app.integrations.object_store import SyncS3ObjectStore
from app.knowledge.resume_extraction import extract_text, looks_like_resume
from app.schemas.recruitment import (
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationStatusOut,
    CandidateProfile,
    DecisionRequest,
    EvaluationDetail,
    EvaluationOut,
    Requirement,
    ScoreFactor,
    VacancyCreate,
    VacancyOut,
)

router = APIRouter(prefix="/api", tags=["recruitment"])

MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_RESUME_TYPES = (".pdf", ".docx")


def _to_detail(raw_payload: dict | None) -> EvaluationDetail | None:
    """Build a typed EvaluationDetail from a stored raw evaluation payload, or None if absent.

    The LLM's raw payload uses camelCase keys (`matchScore`, `scoreFactors`,
    ...); translated explicitly here rather than via a Pydantic alias
    generator, matching the wire format (snake_case) every other field in
    this API uses.
    """
    if not raw_payload:
        return None
    profile = raw_payload.get("candidateProfile")
    return EvaluationDetail(
        requirements=[
            Requirement(**r) for r in raw_payload.get("requirements", []) if isinstance(r, dict)
        ],
        requirements_met=raw_payload.get("requirementsMet", True),
        match_score=raw_payload.get("matchScore", 0),
        recommendation=raw_payload.get("recommendation", ""),
        summary=raw_payload.get("summary", ""),
        score_factors=[
            ScoreFactor(**f) for f in raw_payload.get("scoreFactors", []) if isinstance(f, dict)
        ],
        strengths=raw_payload.get("strengths", []),
        weaknesses=raw_payload.get("weaknesses", []),
        matched_keywords=raw_payload.get("matchedKeywords", []),
        missing_keywords=raw_payload.get("missingKeywords", []),
        candidate_profile=CandidateProfile(**profile) if isinstance(profile, dict) else None,
    )


def _to_application_out(application, evaluation=None) -> ApplicationOut:
    """Build a manager-facing response model for an application, attaching its AI screening result."""
    return ApplicationOut(
        application_id=application.application_id,
        vacancy_id=application.vacancy_id,
        vacancy_title=application.vacancy.title if application.vacancy else None,
        application_status=application.application_status,
        applied_at=application.applied_at,
        evaluated=evaluation is not None,
        evaluation=(
            EvaluationOut(
                score=evaluation.score,
                overview=evaluation.overview,
                model=evaluation.model,
                evaluated_at=evaluation.evaluated_at,
                detail=_to_detail(evaluation.raw_payload),
            )
            if evaluation is not None
            else None
        ),
    )


def _to_application_detail_out(svc: RecruitmentService, application) -> ApplicationDetailOut:
    """Build a manager-facing detail response: application + evaluation + candidate contact info."""
    evaluation = svc.latest_evaluation(application.application_id)
    payload = _to_application_out(application, evaluation).model_dump()
    candidate = svc._identity.get_candidate_for_application(application)
    # A linked Employee row means the candidate was hired from this pipeline
    # (the application status itself stays SHORTLISTED).
    payload["hired"] = candidate.hired_employee_id is not None if candidate else False
    return ApplicationDetailOut(
        **payload,
        candidate_name=_candidate_display(svc, candidate),
        candidate_email=_candidate_email(svc, candidate),
    )


def _to_status_out(application) -> ApplicationStatusOut:
    """Build a candidate-facing response: status only, no AI screening result."""
    return ApplicationStatusOut(
        application_id=application.application_id,
        vacancy_id=application.vacancy_id,
        vacancy_title=application.vacancy.title if application.vacancy else None,
        application_status=application.application_status,
        applied_at=application.applied_at,
    )


def _svc(db=Depends(get_db)) -> RecruitmentService:
    """FastAPI dependency that builds a RecruitmentService bound to the request's DB session."""
    return RecruitmentService(db)


def _department_name(svc: RecruitmentService, department_id: uuid.UUID) -> str | None:
    """Resolve a department id to its display name, or None if it no longer exists."""
    dept = svc._db.get(Department, department_id)
    return dept.name if dept else None


def _candidate_display(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's full display name, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    person = svc._db.get(Person, candidate.person_id)
    return f"{person.first_name} {person.last_name}".strip() if person else None


def _candidate_email(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's email address, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    person = svc._db.get(Person, candidate.person_id)
    return person.email if person else None


def _vacancy_out(v) -> VacancyOut:
    """Build a VacancyOut from a Vacancy row (department name resolved separately)."""
    return VacancyOut(
        vacancy_id=v.vacancy_id,
        title=v.title,
        department_name=None,
        description=v.description,
        employment_type=v.employment_type,
        opening_date=v.opening_date,
        closing_date=v.closing_date,
        status=v.status,
        created_at=v.created_at,
    )


# ---- vacancies --------------------------------------------------------


@router.get("/vacancies", response_model=list[VacancyOut])
def list_vacancies(
    user: UserContext | None = Depends(get_optional_user),
    svc: RecruitmentService = Depends(_svc),
):
    """List vacancies; anonymous visitors and candidates see only open ones."""
    vacancies = svc.list_vacancies(user)
    depts = {v.department_id: _department_name(svc, v.department_id) for v in vacancies}
    out = []
    for v in vacancies:
        vo = _vacancy_out(v)
        vo.department_name = depts.get(v.department_id)
        out.append(vo)
    return out


@router.post("/vacancies", response_model=VacancyOut, status_code=status.HTTP_201_CREATED)
def create_vacancy(
    body: VacancyCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Create a new vacancy (manager-only)."""
    try:
        vacancy = svc.create_vacancy(
            user,
            title=body.title,
            department_name=body.department_name,
            description=body.description,
            employment_type=body.employment_type,
            opening_date=body.opening_date,
            closing_date=body.closing_date,
        )
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = body.department_name
    return vo


@router.get("/vacancies/{vacancy_id}", response_model=VacancyOut)
def get_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext | None = Depends(get_optional_user),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single vacancy by id, or 404 if not found (public — job postings)."""
    vacancy = svc.get_vacancy(vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found.")
    vo = _vacancy_out(vacancy)
    vo.department_name = _department_name(svc, vacancy.department_id)
    return vo


@router.post("/vacancies/{vacancy_id}/close", response_model=VacancyOut)
def close_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Archive a vacancy: move it to CLOSED while keeping its applications (manager-only)."""
    try:
        vacancy = svc.archive_vacancy(user, vacancy_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = _department_name(svc, vacancy.department_id)
    return vo


@router.post("/vacancies/{vacancy_id}/reopen", response_model=VacancyOut)
def reopen_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Re-open an archived (CLOSED) vacancy so candidates can apply again (manager-only)."""
    try:
        vacancy = svc.reopen_vacancy(user, vacancy_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = _department_name(svc, vacancy.department_id)
    return vo


# ---- applications ------------------------------------------------------


@router.post(
    "/vacancies/{vacancy_id}/applications",
    response_model=ApplicationStatusOut,
    status_code=status.HTTP_201_CREATED,
)
def apply_to_vacancy(
    vacancy_id: uuid.UUID,
    file: UploadFile,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Apply to a vacancy (candidate-only): validates and stores the resume, then creates the application.

    Plain `def` (not `async def`) so FastAPI runs the blocking MinIO upload
    and DB commit in its threadpool instead of on the shared event loop.
    """
    data = file.file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="Resume too large. Max size is 10MB.")
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_RESUME_TYPES):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX resumes are accepted.")

    extraction = extract_text(data, filename, file.content_type or "")
    is_resume, reason = looks_like_resume(extraction.text)
    if not is_resume:
        raise HTTPException(status_code=400, detail=reason)

    # upload to MinIO FIRST; only then create the application row
    try:
        object_key = SyncS3ObjectStore().put_resume(data, filename, file.content_type or "")
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to store resume.") from err

    try:
        application = svc.apply(user, vacancy_id=vacancy_id, cv_object_key=object_key)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return _to_status_out(application)


@router.post(
    "/vacancies/{vacancy_id}/apply",
    response_model=ApplicationStatusOut,
    status_code=status.HTTP_201_CREATED,
)
def apply_as_new_candidate(
    vacancy_id: uuid.UUID,
    file: UploadFile,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str | None = Form(None),
    password: str = Form(...),
    svc: RecruitmentService = Depends(_svc),
):
    """Apply to an open vacancy as a new (anonymous) candidate.

    No login required: the candidate's details + resume are collected here and
    their account (password chosen in the form) is provisioned in the same
    transaction as the application. Blocks when the email already exists —
    that person should sign in and use the authenticated apply flow instead.

    Plain `def` (not `async def`) so FastAPI runs the blocking MinIO upload
    and DB commit in its threadpool instead of on the shared event loop.
    """
    data = file.file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="Resume too large. Max size is 10MB.")
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_RESUME_TYPES):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX resumes are accepted.")

    extraction = extract_text(data, filename, file.content_type or "")
    is_resume, reason = looks_like_resume(extraction.text)
    if not is_resume:
        raise HTTPException(status_code=400, detail=reason)

    # upload to MinIO FIRST; only then provision the account + application row
    try:
        object_key = SyncS3ObjectStore().put_resume(data, filename, file.content_type or "")
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to store resume.") from err

    try:
        application = svc.apply_as_new_candidate(
            vacancy_id=vacancy_id,
            cv_object_key=object_key,
            first_name=first_name,
            last_name=last_name,
            email=email,
            phone=phone,
            password=password,
        )
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except IntegrityError as err:
        # Two concurrent submissions with the same email racing the unique
        # constraint on Person.email — the duplicate-email guard above usually
        # catches it, this is the last-resort backstop.
        raise HTTPException(
            status_code=409, detail="An account already exists for this email — sign in instead."
        ) from err

    return _to_status_out(application)


@router.get("/applications/mine", response_model=list[ApplicationStatusOut])
def my_applications(
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """List the current candidate's applications — status only, no AI screening result."""
    applications = svc.list_my_applications(user)
    return [_to_status_out(a) for a in applications]


@router.get("/applications/mine/{application_id}", response_model=ApplicationStatusOut)
def my_application(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return one of the current candidate's applications by id — status only."""
    try:
        application = svc.get_my_application(user, application_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return _to_status_out(application)


@router.get("/applications", response_model=list[ApplicationDetailOut])
def all_applications(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """List every application across all vacancies, including candidate details (manager-only)."""
    applications = svc.list_all_applications(user)
    return [_to_application_detail_out(svc, a) for a in applications]


@router.get(
    "/vacancies/{vacancy_id}/applications", response_model=list[ApplicationDetailOut]
)
def vacancy_applications(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """List all applications for a vacancy, including candidate details (manager-only)."""
    try:
        applications = svc.list_vacancy_applications(user, vacancy_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return [_to_application_detail_out(svc, a) for a in applications]


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
def application_detail(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single application for review, with its evaluation and candidate details."""
    try:
        application = svc.get_application_for_review(user, application_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return _to_application_detail_out(svc, application)


@router.get("/applications/{application_id}/resume")
def download_resume(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Stream the stored resume file for an application (manager-only)."""
    try:
        application = svc.get_application_for_review(user, application_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    if not application.cv_object_key:
        raise HTTPException(status_code=404, detail="No resume on file.")
    try:
        data, content_type = SyncS3ObjectStore().get_object(application.cv_object_key)
    except FileNotFoundError as err:
        raise HTTPException(status_code=404, detail="Resume object missing from storage.") from err
    filename = application.cv_object_key.rsplit("/", 1)[-1]
    return Response(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/applications/{application_id}/decision", response_model=ApplicationOut)
def decide_application(
    application_id: uuid.UUID,
    body: DecisionRequest,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Approve or reject an application (manager-only)."""
    if body.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'.")
    try:
        application = svc.decide_application(user, application_id, approve=body.action == "approve")
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return _to_application_out(application, svc.latest_evaluation(application_id))
