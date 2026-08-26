from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_optional_user, require_role
from app.capabilities.recruitment import PermissionError_, RecruitmentService
from app.capabilities.settings import SettingsService
from app.contracts.auth import UserContext
from app.db.session import get_db
from app.domain.identity import Department, Person
from app.evaluation.keyword_suggestion import suggest_keywords
from app.integrations.object_store import SyncS3ObjectStore
from app.knowledge.resume_extraction import extract_text, is_ats_friendly, looks_like_resume
from app.model_gateway.provider import ChatProviderError
from app.schemas.recruitment import (
    ApplicationDetailOut,
    ApplicationOut,
    ApplicationStatusOut,
    CandidateProfile,
    DecisionRequest,
    EducationOut,
    EvaluationDetail,
    EvaluationOut,
    KeyFactor,
    KeywordMatch,
    KeywordSuggestionOut,
    KeywordSuggestionRequest,
    Requirement,
    ScoringKeyword,
    StructuredResumeOut,
    VacancyCreate,
    VacancyOut,
    WorkExperienceOut,
)

router = APIRouter(prefix="/api", tags=["recruitment"])

MAX_RESUME_BYTES = 10 * 1024 * 1024  # 10MB
ALLOWED_RESUME_TYPES = (".pdf", ".docx")


def _to_structured_resume(raw: dict | None) -> StructuredResumeOut | None:
    """Build a typed StructuredResumeOut from the stored structuring result, or None if absent."""
    if not isinstance(raw, dict):
        return None
    return StructuredResumeOut(
        work_experience=[
            WorkExperienceOut(
                title=e.get("title", ""),
                company=e.get("company", ""),
                start_date=e.get("start_date", ""),
                end_date=e.get("end_date", ""),
                start_year=e.get("start_year"),
                end_year=e.get("end_year"),
                is_current=bool(e.get("is_current", False)),
            )
            for e in raw.get("work_experience", [])
            if isinstance(e, dict)
        ],
        education=[
            EducationOut(
                degree=e.get("degree", ""),
                institution=e.get("institution", ""),
                graduation_year=e.get("graduation_year"),
            )
            for e in raw.get("education", [])
            if isinstance(e, dict)
        ],
        skills=raw.get("skills", []),
        total_years_experience=raw.get("total_years_experience", 0.0),
    )


def _to_detail(raw_payload: dict | None) -> EvaluationDetail | None:
    """Build a typed EvaluationDetail from a stored raw evaluation payload, or None if absent."""
    if not raw_payload:
        return None
    profile = raw_payload.get("candidateProfile")
    return EvaluationDetail(
        requirements=[
            Requirement(**r) for r in raw_payload.get("requirements", []) if isinstance(r, dict)
        ],
        requirements_met=raw_payload.get("requirementsMet", True),
        recommendation=raw_payload.get("recommendation", ""),
        summary=raw_payload.get("summary", ""),
        key_factors=[
            KeyFactor(**f) for f in raw_payload.get("keyFactors", []) if isinstance(f, dict)
        ],
        strengths=raw_payload.get("strengths", []),
        weaknesses=raw_payload.get("weaknesses", []),
        matched_keywords=raw_payload.get("matchedKeywords", []),
        missing_keywords=raw_payload.get("missingKeywords", []),
        keyword_matches=[
            KeywordMatch(**m) for m in raw_payload.get("keywordMatches", []) if isinstance(m, dict)
        ],
        candidate_profile=CandidateProfile(**profile) if isinstance(profile, dict) else None,
        structured_resume=_to_structured_resume(raw_payload.get("structuredResume")),
    )


def _to_application_out(application, evaluation=None) -> ApplicationOut:
    """Build a manager-facing response model for an application, attaching its AI screening result."""
    return ApplicationOut(
        application_id=application.application_id,
        vacancy_id=application.vacancy_id,
        vacancy_title=application.vacancy.title if application.vacancy else None,
        application_status=application.application_status,
        applied_at=application.applied_at,
        withdrawn_at=application.withdrawn_at,
        evaluated=evaluation is not None,
        evaluation=(
            EvaluationOut(
                overview=evaluation.overview,
                failed=evaluation.failed,
                keyword_score=evaluation.keyword_score,
                model=evaluation.model,
                evaluated_at=evaluation.evaluated_at,
                detail=_to_detail(evaluation.raw_payload),
            )
            if evaluation is not None
            else None
        ),
    )


async def _to_application_detail_out(svc: RecruitmentService, application) -> ApplicationDetailOut:
    """Build a manager-facing detail response: application + evaluation + candidate contact info."""
    evaluation = await svc.latest_evaluation(application.application_id)
    payload = _to_application_out(application, evaluation).model_dump()
    candidate = await svc._identity.get_candidate_for_application(application)
    payload["hired"] = candidate.hired_employee_id is not None if candidate else False
    cand_name = await _candidate_display(svc, candidate)
    cand_email = await _candidate_email(svc, candidate)
    return ApplicationDetailOut(
        **payload,
        candidate_name=cand_name,
        candidate_email=cand_email,
    )


async def _to_status_out(application, db: AsyncSession | None = None) -> ApplicationStatusOut:
    """Build a candidate-facing response: status only, no AI screening result."""
    vacancy_title = None
    try:
        if application.vacancy is not None:
            vacancy_title = application.vacancy.title
    except Exception:
        pass
    if vacancy_title is None and db is not None and getattr(application, "vacancy_id", None) is not None:
        try:
            vac = await db.get(Vacancy, application.vacancy_id)
            if vac is not None:
                vacancy_title = vac.title
        except Exception:
            pass

    return ApplicationStatusOut(
        application_id=application.application_id,
        vacancy_id=application.vacancy_id,
        vacancy_title=vacancy_title,
        application_status=application.application_status,
        applied_at=application.applied_at,
        withdrawn_at=application.withdrawn_at,
    )



def _svc(db: AsyncSession = Depends(get_db)) -> RecruitmentService:
    """FastAPI dependency that builds a RecruitmentService bound to the request's DB session."""
    return RecruitmentService(db)


async def _department_name(svc: RecruitmentService, department_id: uuid.UUID) -> str | None:
    """Resolve a department id to its display name, or None if it no longer exists."""
    dept = await svc._db.get(Department, department_id)
    return dept.name if dept else None


async def _candidate_display(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's full display name, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    person = await svc._db.get(Person, candidate.person_id)
    return f"{person.first_name} {person.last_name}".strip() if person else None


async def _candidate_email(svc: RecruitmentService, candidate) -> str | None:
    """Return the candidate's email address, or None if the candidate/person is unknown."""
    if candidate is None:
        return None
    person = await svc._db.get(Person, candidate.person_id)
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
        scoring_keywords=v.scoring_keywords or [],
        created_at=v.created_at,
    )


# ---- vacancies --------------------------------------------------------


@router.get("/vacancies", response_model=list[VacancyOut])
async def list_vacancies(
    user: UserContext | None = Depends(get_optional_user),
    svc: RecruitmentService = Depends(_svc),
):
    """List vacancies; anonymous visitors and candidates see only open ones."""
    vacancies = await svc.list_vacancies(user)
    depts = {v.department_id: await _department_name(svc, v.department_id) for v in vacancies}
    out = []
    for v in vacancies:
        vo = _vacancy_out(v)
        vo.department_name = depts.get(v.department_id)
        out.append(vo)
    return out


@router.post("/vacancies", response_model=VacancyOut, status_code=status.HTTP_201_CREATED)
async def create_vacancy(
    body: VacancyCreate,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Create a new vacancy (manager-only)."""
    try:
        vacancy = await svc.create_vacancy(
            user,
            title=body.title,
            department_name=body.department_name,
            description=body.description,
            employment_type=body.employment_type,
            opening_date=body.opening_date,
            closing_date=body.closing_date,
            scoring_keywords=[kw.model_dump() for kw in body.scoring_keywords],
        )
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = body.department_name
    return vo


@router.post("/vacancies/keywords/suggest", response_model=KeywordSuggestionOut)
async def suggest_vacancy_keywords(
    body: KeywordSuggestionRequest,
    user: UserContext = Depends(require_role("HR_ADMIN")),
):
    """Suggest scoring keywords + tiers from a job title/description (manager-only)."""
    settings_svc = SettingsService()
    llm_overrides = settings_svc.resolved_llm_overrides()
    try:
        result = await suggest_keywords(
            body.title,
            body.description,
            api_base=llm_overrides["api_base"],
            model=llm_overrides["model"],
            api_key=llm_overrides["api_key"],
            system_prompt=settings_svc.resolved_keyword_suggestion_prompt(),
        )
    except ChatProviderError as err:
        raise HTTPException(status_code=502, detail=str(err)) from err
    return KeywordSuggestionOut(
        keywords=[ScoringKeyword(keyword=kw.keyword, tier=kw.tier) for kw in result.keywords]
    )


@router.get("/vacancies/{vacancy_id}", response_model=VacancyOut)
async def get_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext | None = Depends(get_optional_user),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single vacancy by id, or 404 if not found (public — job postings)."""
    vacancy = await svc.get_vacancy(vacancy_id)
    if vacancy is None:
        raise HTTPException(status_code=404, detail="Vacancy not found.")
    vo = _vacancy_out(vacancy)
    vo.department_name = await _department_name(svc, vacancy.department_id)
    return vo


@router.post("/vacancies/{vacancy_id}/close", response_model=VacancyOut)
async def close_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Archive a vacancy: move it to CLOSED while keeping its applications (manager-only)."""
    try:
        vacancy = await svc.archive_vacancy(user, vacancy_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = await _department_name(svc, vacancy.department_id)
    return vo


@router.post("/vacancies/{vacancy_id}/reopen", response_model=VacancyOut)
async def reopen_vacancy(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Re-open an archived (CLOSED) vacancy so candidates can apply again (manager-only)."""
    try:
        vacancy = await svc.reopen_vacancy(user, vacancy_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    vo = _vacancy_out(vacancy)
    vo.department_name = await _department_name(svc, vacancy.department_id)
    return vo


# ---- applications ------------------------------------------------------


@router.post(
    "/vacancies/{vacancy_id}/applications",
    response_model=ApplicationStatusOut,
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

    extraction = extract_text(data, filename, file.content_type or "")
    is_resume, reason = await looks_like_resume(extraction.text)
    if not is_resume:
        raise HTTPException(status_code=400, detail=reason)
    is_parsable, parsability_reason = await is_ats_friendly(extraction.text)
    if not is_parsable:
        raise HTTPException(status_code=400, detail=parsability_reason)

    try:
        object_key = SyncS3ObjectStore().put_resume(data, filename, file.content_type or "")
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to store resume.") from err

    try:
        application = await svc.apply(user, vacancy_id=vacancy_id, cv_object_key=object_key)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err

    return await _to_status_out(application, db=svc._db)


@router.post(
    "/vacancies/{vacancy_id}/apply",
    response_model=ApplicationStatusOut,
    status_code=status.HTTP_201_CREATED,
)
async def apply_as_new_candidate(
    vacancy_id: uuid.UUID,
    file: UploadFile,
    first_name: str = Form(...),
    last_name: str = Form(...),
    email: str = Form(...),
    phone: str | None = Form(None),
    password: str = Form(...),
    svc: RecruitmentService = Depends(_svc),
):
    """Apply to an open vacancy as a new (anonymous) candidate."""
    data = await file.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="The uploaded resume is empty.")
    if len(data) > MAX_RESUME_BYTES:
        raise HTTPException(status_code=400, detail="Resume too large. Max size is 10MB.")
    filename = file.filename or ""
    if not filename.lower().endswith(ALLOWED_RESUME_TYPES):
        raise HTTPException(status_code=400, detail="Only PDF or DOCX resumes are accepted.")

    extraction = extract_text(data, filename, file.content_type or "")
    is_resume, reason = await looks_like_resume(extraction.text)
    if not is_resume:
        raise HTTPException(status_code=400, detail=reason)
    is_parsable, parsability_reason = await is_ats_friendly(extraction.text)
    if not is_parsable:
        raise HTTPException(status_code=400, detail=parsability_reason)

    try:
        object_key = SyncS3ObjectStore().put_resume(data, filename, file.content_type or "")
    except Exception as err:
        raise HTTPException(status_code=500, detail="Failed to store resume.") from err

    try:
        application = await svc.apply_as_new_candidate(
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
        raise HTTPException(
            status_code=409, detail="An account already exists for this email — sign in instead."
        ) from err

    return await _to_status_out(application, db=svc._db)


@router.get("/applications/mine", response_model=list[ApplicationStatusOut])
async def my_applications(
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """List the current candidate's applications — status only, no AI screening result."""
    applications = await svc.list_my_applications(user)
    return [await _to_status_out(a, db=svc._db) for a in applications]


@router.get("/applications/mine/{application_id}", response_model=ApplicationStatusOut)
async def my_application(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return one of the current candidate's applications by id — status only."""
    try:
        application = await svc.get_my_application(user, application_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return await _to_status_out(application, db=svc._db)


@router.post("/applications/mine/{application_id}/withdraw", response_model=ApplicationStatusOut)
@router.post("/applications/{application_id}/withdraw", response_model=ApplicationStatusOut)
async def withdraw_application(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("CANDIDATE")),
    svc: RecruitmentService = Depends(_svc),
):
    """Withdraw one of the current candidate's own active applications."""
    try:
        application = await svc.withdraw_application(user, application_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        if str(err) == "Application not found.":
            raise HTTPException(status_code=404, detail=str(err)) from err
        raise HTTPException(status_code=400, detail=str(err)) from err
    return await _to_status_out(application, db=svc._db)



@router.get("/applications", response_model=list[ApplicationDetailOut])
async def all_applications(
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """List every application across all vacancies, including candidate details (manager-only)."""
    applications = await svc.list_all_applications(user)
    return [await _to_application_detail_out(svc, a) for a in applications]


@router.get(
    "/vacancies/{vacancy_id}/applications", response_model=list[ApplicationDetailOut]
)
async def vacancy_applications(
    vacancy_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """List all applications for a vacancy, including candidate details (manager-only)."""
    try:
        applications = await svc.list_vacancy_applications(user, vacancy_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return [await _to_application_detail_out(svc, a) for a in applications]


@router.get("/applications/{application_id}", response_model=ApplicationDetailOut)
async def application_detail(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Return a single application for review, with its evaluation and candidate details."""
    try:
        application = await svc.get_application_for_review(user, application_id)
    except ValueError as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    return await _to_application_detail_out(svc, application)


@router.get("/applications/{application_id}/resume")
async def download_resume(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Stream the stored resume file for an application (manager-only)."""
    try:
        application = await svc.get_application_for_review(user, application_id)
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
async def decide_application(
    application_id: uuid.UUID,
    body: DecisionRequest,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Approve or reject an application (manager-only)."""
    if body.action not in {"approve", "reject"}:
        raise HTTPException(status_code=400, detail="action must be 'approve' or 'reject'.")
    try:
        application = await svc.decide_application(user, application_id, approve=body.action == "approve")
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return _to_application_out(application, await svc.latest_evaluation(application_id))


@router.post("/applications/{application_id}/re-evaluate", response_model=ApplicationOut)
async def re_evaluate_application(
    application_id: uuid.UUID,
    user: UserContext = Depends(require_role("HR_ADMIN")),
    svc: RecruitmentService = Depends(_svc),
):
    """Re-run the AI screening for an application (manager-only)."""
    try:
        application = await svc.re_evaluate_application(user, application_id)
    except PermissionError_ as err:
        raise HTTPException(status_code=403, detail=str(err)) from err
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return _to_application_out(application, await svc.latest_evaluation(application_id))

