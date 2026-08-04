from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from fastapi.responses import Response

from app.api.deps import get_current_user, require_role
from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.integrations.object_store import ObjectStore
from app.schemas.recruitment import (
    ApplicationDetailOut,
    ApplicationOut,
    DecisionRequest,
    EvaluationOut,
    VacancyCreate,
    VacancyOut,
)

router = APIRouter(prefix="/api", tags=["recruitment"])

MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_RESUME_TYPES = (
    ".pdf",
    ".docx",
)


def _to_application_out(application, evaluation=None) -> ApplicationOut:
    """Build an API response model for an application, attaching the latest evaluation if present."""
    evaluated = evaluation is not None
    return ApplicationOut(
        application_id=application.application_id,
        vacancy_id=application.vacancy_id,
        vacancy_title=application.vacancy.title if application.vacancy else None,
        application_status=application.application_status,
        applied_at=application.applied_at,
        evaluated=evaluated,
        evaluation=(
            EvaluationOut(
                score=evaluation.score,
                overview=evaluation.overview,
                model=evaluation.model,
                evaluated_at=evaluation.evaluated_at,
            )
            if evaluation is not None
            else None
        ),
    )


def _svc(db=Depends(get_db)) -> RecruitmentService:
    """FastAPI dependency that builds a RecruitmentService bound to the request's DB session."""
    return RecruitmentService(db)


# ---- vacancies --------------------------------------------------------


@router.get("/vacancies", response_model=list[VacancyOut])
def list_vacancies(
    user: UserContext = Depends(get_current_user),
    svc: RecruitmentService = Depends(_svc),
):
    """List vacancies; candidates see only open ones, employees/managers see all."""
    vacancies = svc.list_vacancies(user)
    depts = {v.department_id: _department_name(svc, v.department_id) for v in vacancies}
    return [
        VacancyOut(
            vacancy_id=v.vacancy_id,
            title=v.title,
            department_name=depts.get(v.department_id),
            description=v.description,
            employment_type=v.employment_type,
            opening_date=v.opening_date,
            closing_date=v.closing_date,
            status=v.status,
            created_at=v.created_at,
        )
        for v in vacancies
    ]


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
    return VacancyOut(
        vacancy_id=vacancy.vacancy_id,
        title=vacancy.title,
        department_name=body.department_name,
        description=vacancy.description,
        employment_type=vacancy.employment_type,
        opening_date=vacancy.opening_date,
        closing_date=vacancy.closing_date,
        status=vacancy.status,
        created_at=vacancy.created_at,
    )


@router.get("/vacancies/{vacancy_id}", response_model=VacancyOut)
def get_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(get_current_user),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single vacancy by id, or 404 if not found."""
    vacancy = svc.get_vacancy(vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found.")
    return VacancyOut(
        vacancy_id=vacancy.vacancy_id,
        title=vacancy.title,
        department_name=_department_name(svc, vacancy.department_id),
        description=vacancy.description,
        employment_type=vacancy.employment_type,
        opening_date=vacancy.opening_date,
        closing_date=vacancy.closing_date,
        status=vacancy.status,
        created_at=vacancy.created_at,
    )


# ---- applications ------------------------------------------------------


@router.post(
    "/vacancies/{vacancy_id}/applications",
    response_model=ApplicationOut,
    status_code=status.HTTP_201_CREATED,
)
async def apply_to_vacancy(
    vacancy_id: uuid.UUID,
    file: UploadFile,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Apply to a vacancy (candidate-only): validates and stores the resume, then creates the application."""
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="Resume too large. Max size is 10MB.")
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_RESUME_TYPES):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX resumes are accepted.")

    # upload to MinIO FIRST; only then create the application row
    try:
        object_key = ObjectStore().put_resume(data, filename, file.content_type or "")
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to store resume.") from err

    try:
        application = svc.apply(user, vacancy_id=vacancy_id, cv_object_key=object_key)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    except Exception as err:
        raise HTTPException(status_code=500, detail=str(err)) from err

    return _to_application_out(application)


@router.get("/applications/mine", response_model=list[ApplicationOut])
def my_applications(
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """List the current candidate's applications, each with its latest evaluation."""
    applications = svc.list_my_applications(user)
    return [
        _to_application_out(a, svc.latest_evaluation(a.application_id)) for a in applications
    ]


@router.get("/applications/mine/{application_id}", response_model=ApplicationDetailOut)
def my_application(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return one of the current candidate's applications (with evaluation) by id."""
    application = svc.get_my_application(user, application_id)
    evaluation = svc.latest_evaluation(application_id)
    out = _to_application_out(application, evaluation)
    return ApplicationDetailOut(**out.model_dump())


@router.get(
    "/vacancies/{vacancy_id}/applications", response_model=list[ApplicationDetailOut]
)
def vacancy_applications(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """List all applications for a vacancy, including candidate details (manager-only)."""
    applications = svc.list_vacancy_applications(user, vacancy_id)
    result: list[ApplicationDetailOut] = []
    for a in applications:
        evaluation = svc.latest_evaluation(a.application_id)
        out = _to_application_out(a, evaluation)
        candidate = svc._identity.get_candidate_for_application(a)
        result.append(
            ApplicationDetailOut(
                **out.model_dump(),
                candidate_name=_candidate_display(svc, candidate),
                candidate_email=_candidate_email(svc, candidate),
            )
        )
    return result


@router.get(
    "/applications/{application_id}", response_model=ApplicationDetailOut
)
def application_detail(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single application for review, with its evaluation and candidate details."""
    application = svc.get_application_for_review(user, application_id)
    evaluation = svc.latest_evaluation(application_id)
    out = _to_application_out(application, evaluation)
    candidate = svc._identity.get_candidate_for_application(application)
    return ApplicationDetailOut(
        **out.model_dump(),
        candidate_name=_candidate_display(svc, candidate),
        candidate_email=_candidate_email(svc, candidate),
    )


@router.get("/applications/{application_id}/resume")
def download_resume(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Stream the stored resume file for an application (manager-only)."""
    application = svc.get_application_for_review(user, application_id)
    if not application.cv_object_key:
        raise HTTPException(status_code=404, detail="No resume on file.")
    try:
        data, content_type = ObjectStore().get_object(application.cv_object_key)
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


# ---- helpers -----------------------------------------------------------


def _department_name(svc: RecruitmentService, department_id: uuid.UUID) -> str | None:
    """Resolve a department id to its display name, or None if it no longer exists."""
    from app.domain.identity import Department

    dept = svc._db.get(Department, department_id)
    return dept.name if dept else None


def _candidate_display(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's full display name, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    from app.domain.identity import Person

    person = svc._db.get(Person, candidate.person_id)
    return f"{person.first_name} {person.last_name}".strip() if person else None


def _candidate_email(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's email address, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    from app.domain.identity import Person

    person = svc._db.get(Person, candidate.person_id)
    return person.email if person else None
