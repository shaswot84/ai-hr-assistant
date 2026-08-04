from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import UserContext
from app.domain.identity import Department, Person
from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy
from app.repositories.outbox import OutboxRepo
from app.repositories.recruitment import ApplicationRepo, VacancyRepo
from app.services.identity import IdentityService

VALID_APPLICATION_STATUSES = {"APPLIED", "SHORTLISTED", "REJECTED", "WITHDRAWN"}


class PermissionError_(Exception):
    pass


class RecruitmentService:
    """Deterministic recruitment business logic (capability layer).

    Authorization decisions (WHETHER) live here alongside validation and
    business rules. The AI/agent never bypasses these.
    """

    def __init__(self, db: Session) -> None:
        self._db = db
        self._vacancies = VacancyRepo(db)
        self._applications = ApplicationRepo(db)
        self._outbox = OutboxRepo(db)
        self._identity = IdentityService(db)

    # ---- vacancies ---------------------------------------------------

    def create_vacancy(
        self,
        actor: UserContext,
        *,
        title: str,
        department_name: str,
        description: str | None,
        employment_type: str,
        opening_date: date | None,
        closing_date: date | None,
    ) -> Vacancy:
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can create vacancies.")
        employee = self._identity.get_employee(actor)
        department = self._get_or_create_department(department_name)
        now = datetime.now(UTC)
        vacancy = Vacancy(
            title=title.strip(),
            department_id=department.department_id,
            description=description,
            employment_type=employment_type.strip().upper(),
            opening_date=opening_date,
            closing_date=closing_date,
            created_by_employee_id=employee.employee_id,
            approval_status="APPROVED",
            status="OPEN",
            created_at=now,
            updated_at=now,
        )
        self._vacancies.create(vacancy)
        self._db.commit()
        return vacancy

    def list_vacancies(self, actor: UserContext) -> list[Vacancy]:
        if actor.coarse_role == "CANDIDATE":
            return self._vacancies.list_open()
        return self._vacancies.list_all()

    def get_vacancy(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        return self._vacancies.get(vacancy_id)

    # ---- applications ------------------------------------------------

    def apply(
        self,
        actor: UserContext,
        *,
        vacancy_id: uuid.UUID,
        cv_object_key: str,
    ) -> Application:
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can apply.")
        candidate = self._identity.get_candidate(actor)
        vacancy = self._vacancies.get(vacancy_id)
        if vacancy is None or vacancy.status != "OPEN":
            raise ValueError("Vacancy is not open for applications.")
        if self._applications.find_existing(candidate.candidate_id, vacancy_id) is not None:
            raise ValueError("You have already applied to this vacancy.")

        now = datetime.now(UTC)
        application = Application(
            candidate_id=candidate.candidate_id,
            vacancy_id=vacancy_id,
            cv_object_key=cv_object_key,
            application_status="APPLIED",
            applied_at=now,
            updated_at=now,
        )
        self._applications.create(application)
        # same-transaction outbox: AI evaluation
        self._outbox.enqueue(
            "EVALUATE_APPLICATION",
            {"application_id": str(application.application_id), "cv_object_key": cv_object_key},
        )
        self._db.commit()
        return application

    def list_my_applications(self, actor: UserContext) -> list[Application]:
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = self._identity.get_candidate(actor)
        return self._applications.list_for_candidate(candidate.candidate_id)

    def get_my_application(self, actor: UserContext, application_id: uuid.UUID) -> Application:
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = self._identity.get_candidate(actor)
        application = self._applications.get_for_candidate(application_id, candidate.candidate_id)
        if application is None:
            raise ValueError("Application not found.")
        return application

    def list_vacancy_applications(self, actor: UserContext, vacancy_id: uuid.UUID) -> list[Application]:
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        vacancy = self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        return self._applications.list_for_vacancy(vacancy_id)

    def get_application_for_review(
        self, actor: UserContext, application_id: uuid.UUID
    ) -> Application:
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        application = self._applications.get(application_id)
        if application is None:
            raise ValueError("Application not found.")
        return application

    def decide_application(
        self,
        actor: UserContext,
        application_id: uuid.UUID,
        *,
        approve: bool,
    ) -> Application:
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can make hiring decisions.")
        application = self._applications.get(application_id)
        if application is None:
            raise ValueError("Application not found.")
        if application.application_status not in {"APPLIED", "SHORTLISTED", "REJECTED"}:
            raise ValueError(f"Cannot decide an application in state {application.application_status}.")

        now = datetime.now(UTC)
        application.application_status = "SHORTLISTED" if approve else "REJECTED"
        if not approve:
            application.rejected_at = now
        application.updated_at = now
        self._applications.save(application)

        # same-transaction outbox: notification email
        if approve:
            job_type, subject, body = self._build_email_payload(application, approve=True)
        else:
            job_type, subject, body = self._build_email_payload(application, approve=False)
        self._outbox.enqueue(job_type, {"application_id": str(application.application_id), "to_email": self._candidate_email(application), "subject": subject, "body": body})

        self._db.commit()
        return application

    def latest_evaluation(self, application_id: uuid.UUID) -> ApplicationEvaluation | None:
        return self._applications.latest_evaluation(application_id)

    # ---- helpers -----------------------------------------------------

    def _candidate_email(self, application: Application) -> str:
        candidate = self._identity.get_candidate_for_application(application)
        if candidate is None:
            return ""
        person = self._db.get(Person, candidate.person_id)
        return person.email if person else ""

    def _build_email_payload(
        self, application: Application, *, approve: bool
    ) -> tuple[str, str, str]:
        vacancy = application.vacancy
        title = vacancy.title if vacancy else "the position"
        if approve:
            return (
                "SEND_INTERVIEW_INVITATION",
                f"Application update: shortlisted for {title}",
                (
                    f"Congratulations! Your application for {title} has been shortlisted. "
                    "You will be further notified about interview scheduling. "
                    "Thank you for your interest."
                ),
            )
        return (
            "SEND_APPLICATION_REJECTED",
            f"Application update: {title}",
            (
                f"Thank you for applying to {title}. After careful review, we have decided "
                "to move forward with other candidates whose qualifications more closely "
                "match this role. We appreciate your interest."
            ),
        )

    def _get_or_create_department(self, name: str):
        stmt = select(Department).where(Department.name == name.strip())
        dept = self._db.scalar(stmt)
        if dept is not None:
            return dept
        dept = Department(name=name.strip())
        self._db.add(dept)
        self._db.flush()
        return dept
