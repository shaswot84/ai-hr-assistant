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
    """Raised when a caller lacks the authority to perform a recruitment operation."""


class RecruitmentService:
    """Deterministic recruitment business logic (capability layer).

    Authorization decisions (WHETHER) live here alongside validation and
    business rules. The AI/agent never bypasses these.
    """

    def __init__(self, db: Session) -> None:
        """Bind the service to a DB session and build its repositories."""
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
        """Create an open vacancy (HR_ADMIN only), auto-creating the department if needed."""
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
        """List vacancies; candidates see only open ones, others see everything."""
        if actor.coarse_role == "CANDIDATE":
            return self._vacancies.list_open()
        return self._vacancies.list_all()

    def get_vacancy(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        """Fetch a single vacancy by id, or None if it does not exist."""
        return self._vacancies.get(vacancy_id)

    def archive_vacancy(self, actor: UserContext, vacancy_id: uuid.UUID) -> Vacancy:
        """Move a vacancy to CLOSED (archived), keeping all of its applications.

        An archived vacancy no longer accepts applications but remains visible
        to managers with its full application history.
        """
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can archive vacancies.")
        vacancy = self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        if vacancy.status == "CLOSED":
            return vacancy
        vacancy.status = "CLOSED"
        vacancy.updated_at = datetime.now(UTC)
        self._vacancies.save(vacancy)
        self._db.commit()
        return vacancy

    def reopen_vacancy(self, actor: UserContext, vacancy_id: uuid.UUID) -> Vacancy:
        """Re-open an archived (CLOSED) vacancy so candidates can apply again."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can reopen vacancies.")
        vacancy = self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        if vacancy.status == "OPEN":
            return vacancy
        vacancy.status = "OPEN"
        vacancy.updated_at = datetime.now(UTC)
        self._vacancies.save(vacancy)
        self._db.commit()
        return vacancy

    # ---- applications ------------------------------------------------

    def apply(
        self,
        actor: UserContext,
        *,
        vacancy_id: uuid.UUID,
        cv_object_key: str,
    ) -> Application:
        """Create an application for a candidate on an open vacancy they have not already applied to.

        Enqueues an AI-evaluation outbox job in the same transaction as the application row.
        """
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
        """List the current candidate's own applications."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = self._identity.get_candidate(actor)
        return self._applications.list_for_candidate(candidate.candidate_id)

    def get_my_application(self, actor: UserContext, application_id: uuid.UUID) -> Application:
        """Fetch one of the current candidate's applications, or raise if not theirs/not found."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = self._identity.get_candidate(actor)
        application = self._applications.get_for_candidate(application_id, candidate.candidate_id)
        if application is None:
            raise ValueError("Application not found.")
        return application

    def list_vacancy_applications(self, actor: UserContext, vacancy_id: uuid.UUID) -> list[Application]:
        """List all applications for a vacancy (HR_ADMIN only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        vacancy = self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        return self._applications.list_for_vacancy(vacancy_id)

    def get_application_for_review(
        self, actor: UserContext, application_id: uuid.UUID
    ) -> Application:
        """Fetch an application for manager review, or raise if not found."""
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
        """Approve (shortlist) or reject an application and enqueue the notification email.

        The status transition and the outbox email job commit in one transaction.
        """
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
        """Return the most recent evaluation for an application, or None if not yet evaluated."""
        return self._applications.latest_evaluation(application_id)

    # ---- helpers -----------------------------------------------------

    def _candidate_email(self, application: Application) -> str:
        """Resolve the candidate's email address for an application."""
        candidate = self._identity.get_candidate_for_application(application)
        if candidate is None:
            return ""
        person = self._db.get(Person, candidate.person_id)
        return person.email if person else ""

    def _build_email_payload(
        self, application: Application, *, approve: bool
    ) -> tuple[str, str, str]:
        """Build the outbox job type, subject, and body for an approve/reject notification."""
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
        """Return the department matching `name`, creating it if it does not yet exist."""
        stmt = select(Department).where(Department.name == name.strip())
        dept = self._db.scalar(stmt)
        if dept is not None:
            return dept
        dept = Department(name=name.strip())
        self._db.add(dept)
        self._db.flush()
        return dept
