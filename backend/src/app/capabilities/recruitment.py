from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.passwords import hash_password
from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Candidate, Department, Employee, Person
from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy
from app.repositories.audit import AuditRepo
from app.repositories.outbox import OutboxRepo
from app.repositories.recruitment import ApplicationRepo, VacancyRepo
from app.services.identity import IdentityService
from app.shared.clock import Clock, get_clock

# Decisions are only valid from APPLIED — SHORTLISTED/REJECTED are terminal
# for this week's flow (no re-review), so a decision can never be replayed
# into a second candidate-facing email or leave a stale rejected_at behind.
DECIDABLE_STATUSES = {"APPLIED"}
WITHDRAWABLE_STATUSES = {"APPLIED", "SHORTLISTED"}


class PermissionError_(Exception):
    """Raised when a caller lacks the authority to perform a recruitment operation."""


class RecruitmentService:
    """Deterministic recruitment business logic (capability layer)."""

    def __init__(self, db: AsyncSession, clock: Clock | None = None) -> None:
        """Bind the service to an async DB session and build its repositories."""
        self._db = db
        self._clock = clock or get_clock()
        self._vacancies = VacancyRepo(db)
        self._applications = ApplicationRepo(db)
        self._outbox = OutboxRepo(db, clock=self._clock)
        self._audit = AuditRepo(db, clock=self._clock)
        self._identity = IdentityService(db)

    # ---- vacancies ---------------------------------------------------

    async def create_vacancy(
        self,
        actor: UserContext,
        *,
        title: str,
        department_name: str,
        description: str | None,
        employment_type: str,
        opening_date,
        closing_date,
        scoring_keywords: list[dict],
    ) -> Vacancy:
        """Create an open vacancy (HR_ADMIN only), auto-creating the department if needed."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can create vacancies.")
        employee = await self._identity.get_employee(actor)
        department = await self._get_or_create_department(department_name)
        now = self._clock.now()
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
            scoring_keywords=scoring_keywords,
            created_at=now,
            updated_at=now,
        )
        await self._vacancies.create(vacancy)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="VACANCY_CREATED",
            target_type="vacancy",
            target_id=vacancy.vacancy_id,
            new_state={"title": vacancy.title, "status": vacancy.status},
        )
        await self._db.commit()
        return vacancy

    async def list_vacancies(self, actor: UserContext | None) -> list[Vacancy]:
        """List vacancies; candidates and anonymous visitors see only open ones."""
        if actor is None or actor.coarse_role == "CANDIDATE":
            return await self._vacancies.list_open()
        return await self._vacancies.list_all()

    async def get_vacancy(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        """Fetch a single vacancy by id, or None if it does not exist."""
        return await self._vacancies.get(vacancy_id)

    async def archive_vacancy(self, actor: UserContext, vacancy_id: uuid.UUID) -> Vacancy:
        """Move a vacancy to CLOSED (archived), keeping all of its applications."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can archive vacancies.")
        vacancy = await self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        if vacancy.status == "CLOSED":
            return vacancy
        previous_status = vacancy.status
        vacancy.status = "CLOSED"
        vacancy.updated_at = self._clock.now()
        await self._vacancies.save(vacancy)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="VACANCY_CLOSED",
            target_type="vacancy",
            target_id=vacancy.vacancy_id,
            previous_state={"status": previous_status},
            new_state={"status": "CLOSED"},
        )
        await self._db.commit()
        return vacancy

    async def reopen_vacancy(self, actor: UserContext, vacancy_id: uuid.UUID) -> Vacancy:
        """Re-open an archived (CLOSED) vacancy so candidates can apply again."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can reopen vacancies.")
        vacancy = await self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        if vacancy.status == "OPEN":
            return vacancy
        previous_status = vacancy.status
        vacancy.status = "OPEN"
        vacancy.updated_at = self._clock.now()
        await self._vacancies.save(vacancy)
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="VACANCY_REOPENED",
            target_type="vacancy",
            target_id=vacancy.vacancy_id,
            previous_state={"status": previous_status},
            new_state={"status": "OPEN"},
        )
        await self._db.commit()
        return vacancy

    # ---- applications ------------------------------------------------

    async def apply(
        self,
        actor: UserContext,
        *,
        vacancy_id: uuid.UUID,
        cv_object_key: str,
    ) -> Application:
        """Create an application for a candidate on an open vacancy they have not already applied to."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can apply.")
        candidate = await self._identity.get_candidate(actor)
        vacancy = await self._vacancies.get(vacancy_id)
        if vacancy is None or vacancy.status != "OPEN":
            raise ValueError("Vacancy is not open for applications.")
        if await self._applications.find_existing(candidate.candidate_id, vacancy_id) is not None:
            raise ValueError("You have already applied to this vacancy.")

        now = self._clock.now()
        application = Application(
            candidate_id=candidate.candidate_id,
            vacancy_id=vacancy_id,
            cv_object_key=cv_object_key,
            application_status="APPLIED",
            applied_at=now,
            updated_at=now,
        )
        await self._applications.create(application)
        await self._outbox.enqueue(
            "EVALUATE_APPLICATION",
            {"application_id": str(application.application_id), "cv_object_key": cv_object_key},
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        candidate_email = await self._candidate_email(application)
        await self._outbox.enqueue(
            "SEND_APPLICATION_RECEIVED",
            {
                "application_id": str(application.application_id),
                "to_email": candidate_email,
                "subject": f"Application received: {vacancy.title}",
                "body": (
                    f"Thanks for applying to {vacancy.title}. We've received your resume and "
                    "will notify you once it's been reviewed."
                ),
            },
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        manager_email = await self._manager_email(vacancy)
        if manager_email:
            await self._outbox.enqueue(
                "SEND_NEW_APPLICATION_ALERT",
                {
                    "application_id": str(application.application_id),
                    "to_email": manager_email,
                    "subject": f"New application: {vacancy.title}",
                    "body": (
                        f"A new candidate applied to {vacancy.title}. Review the application "
                        "in the manager portal."
                    ),
                },
                aggregate_type="application",
                aggregate_id=application.application_id,
            )
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="APPLICATION_CREATED",
            target_type="application",
            target_id=application.application_id,
            new_state={"vacancy_id": str(vacancy_id), "status": "APPLIED"},
        )
        await self._db.commit()
        return application

    async def apply_as_new_candidate(
        self,
        *,
        vacancy_id: uuid.UUID,
        cv_object_key: str,
        first_name: str,
        last_name: str,
        email: str,
        phone: str | None,
        password: str,
    ) -> Application:
        """Apply to a vacancy as a brand-new, self-registering candidate."""
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters.")
        vacancy = await self._vacancies.get(vacancy_id)
        if vacancy is None or vacancy.status != "OPEN":
            raise ValueError("Vacancy is not open for applications.")
        normalized_email = email.strip().lower()
        if await self._person_by_email(normalized_email) is not None:
            raise ValueError(
                "An account already exists for this email — sign in and apply from there."
            )

        now = self._clock.now()
        person = Person(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=normalized_email,
            phone=phone.strip() if phone else None,
            created_at=now,
            updated_at=now,
        )
        self._db.add(person)
        await self._db.flush()
        app_user = ApplicationUser(
            external_subject=str(uuid.uuid4()),
            person_id=person.person_id,
            coarse_role="CANDIDATE",
            password_hash=hash_password(password),
            created_at=now,
            updated_at=now,
        )
        self._db.add(app_user)
        await self._db.flush()
        candidate = Candidate(
            person_id=person.person_id,
            registration_date=self._clock.today(),
            created_at=now,
            updated_at=now,
        )
        self._db.add(candidate)
        await self._db.flush()

        application = Application(
            candidate_id=candidate.candidate_id,
            vacancy_id=vacancy_id,
            cv_object_key=cv_object_key,
            application_status="APPLIED",
            applied_at=now,
            updated_at=now,
        )
        await self._applications.create(application)
        await self._outbox.enqueue(
            "EVALUATE_APPLICATION",
            {"application_id": str(application.application_id), "cv_object_key": cv_object_key},
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        await self._outbox.enqueue(
            "SEND_APPLICATION_RECEIVED",
            {
                "application_id": str(application.application_id),
                "to_email": normalized_email,
                "subject": f"Application received: {vacancy.title}",
                "body": (
                    f"Thanks for applying to {vacancy.title}. We've received your resume and "
                    "will notify you once it's been reviewed."
                ),
            },
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        manager_email = await self._manager_email(vacancy)
        if manager_email:
            await self._outbox.enqueue(
                "SEND_NEW_APPLICATION_ALERT",
                {
                    "application_id": str(application.application_id),
                    "to_email": manager_email,
                    "subject": f"New application: {vacancy.title}",
                    "body": (
                        f"A new candidate applied to {vacancy.title}. Review the application "
                        "in the manager portal."
                    ),
                },
                aggregate_type="application",
                aggregate_id=application.application_id,
            )
        await self._audit.record(
            actor_user_id=None,
            action="CANDIDATE_SELF_REGISTERED",
            target_type="candidate",
            target_id=candidate.candidate_id,
            new_state={
                "application_id": str(application.application_id),
                "vacancy_id": str(vacancy_id),
                "status": "APPLIED",
            },
        )
        await self._db.commit()
        return application

    async def list_my_applications(self, actor: UserContext) -> list[Application]:
        """List the current candidate's own applications."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = await self._identity.get_candidate(actor)
        return await self._applications.list_for_candidate(candidate.candidate_id)

    async def get_my_application(self, actor: UserContext, application_id: uuid.UUID) -> Application:
        """Fetch one of the current candidate's applications, or raise if not theirs/not found."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can view their applications.")
        candidate = await self._identity.get_candidate(actor)
        application = await self._applications.get_for_candidate(application_id, candidate.candidate_id)
        if application is None:
            raise ValueError("Application not found.")
        return application

    async def withdraw_application(
        self, actor: UserContext, application_id: uuid.UUID
    ) -> Application:
        """Withdraw one of the current candidate's own active applications."""
        if actor.coarse_role != "CANDIDATE":
            raise PermissionError_("Only candidates can withdraw their applications.")
        candidate = await self._identity.get_candidate(actor)
        application = await self._applications.get_for_candidate(application_id, candidate.candidate_id)
        if application is None:
            raise ValueError("Application not found.")
        if application.application_status == "WITHDRAWN":
            raise ValueError("Application is already withdrawn.")
        if application.application_status not in WITHDRAWABLE_STATUSES:
            raise ValueError(
                f"Cannot withdraw application with status {application.application_status}."
            )

        now = self._clock.now()
        previous_status = application.application_status
        application.application_status = "WITHDRAWN"
        application.withdrawn_at = now
        application.updated_at = now
        await self._applications.save(application)

        vacancy_title = application.vacancy.title if application.vacancy else "the position"
        candidate_email = await self._candidate_email(application)
        await self._outbox.enqueue(
            "SEND_APPLICATION_WITHDRAWN",
            {
                "application_id": str(application.application_id),
                "to_email": candidate_email,
                "subject": f"Application withdrawn: {vacancy_title}",
                "body": (
                    f"Your application for {vacancy_title} has been withdrawn. "
                    "Thank you for your interest and we wish you the best in your job search."
                ),
            },
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="APPLICATION_WITHDRAWN",
            target_type="application",
            target_id=application.application_id,
            previous_state={"status": previous_status},
            new_state={"status": application.application_status},
        )

        await self._db.commit()
        return application

    async def list_all_applications(self, actor: UserContext) -> list[Application]:
        """List every application across all vacancies (HR_ADMIN only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        return await self._applications.list_all()

    async def list_vacancy_applications(self, actor: UserContext, vacancy_id: uuid.UUID) -> list[Application]:
        """List all applications for a vacancy (HR_ADMIN only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        vacancy = await self._vacancies.get(vacancy_id)
        if vacancy is None:
            raise ValueError("Vacancy not found.")
        return await self._applications.list_for_vacancy(vacancy_id)

    async def get_application_for_review(
        self, actor: UserContext, application_id: uuid.UUID
    ) -> Application:
        """Fetch an application for manager review, or raise if not found."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review applications.")
        application = await self._applications.get(application_id)
        if application is None:
            raise ValueError("Application not found.")
        return application

    async def decide_application(
        self,
        actor: UserContext,
        application_id: uuid.UUID,
        *,
        approve: bool,
    ) -> Application:
        """Approve (shortlist) or reject an application and enqueue the notification email."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can make hiring decisions.")
        application = await self._applications.get(application_id)
        if application is None:
            raise ValueError("Application not found.")
        if application.application_status not in DECIDABLE_STATUSES:
            raise ValueError(
                f"Application has already been decided (status={application.application_status})."
            )

        now = self._clock.now()
        previous_status = application.application_status
        application.application_status = "SHORTLISTED" if approve else "REJECTED"
        if not approve:
            application.rejected_at = now
        application.updated_at = now
        await self._applications.save(application)

        job_type, subject, body = self._build_email_payload(application, approve=approve)
        candidate_email = await self._candidate_email(application)
        await self._outbox.enqueue(
            job_type,
            {
                "application_id": str(application.application_id),
                "to_email": candidate_email,
                "subject": subject,
                "body": body,
            },
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="APPLICATION_DECIDED",
            target_type="application",
            target_id=application.application_id,
            previous_state={"status": previous_status},
            new_state={"status": application.application_status},
        )

        await self._db.commit()
        return application

    async def latest_evaluation(self, application_id: uuid.UUID) -> ApplicationEvaluation | None:
        """Return the most recent evaluation for an application, or None if not yet evaluated."""
        return await self._applications.latest_evaluation(application_id)

    async def re_evaluate_application(self, actor: UserContext, application_id: uuid.UUID) -> Application:
        """Re-enqueue the AI screening job for an application (manager-triggered retry)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can re-run a screening.")
        application = await self._applications.get(application_id)
        if application is None:
            raise ValueError("Application not found.")
        if not application.cv_object_key:
            raise ValueError("Application has no resume on file to re-screen.")

        await self._outbox.enqueue(
            "EVALUATE_APPLICATION",
            {"application_id": str(application.application_id), "cv_object_key": application.cv_object_key},
            aggregate_type="application",
            aggregate_id=application.application_id,
        )
        await self._audit.record(
            actor_user_id=await self._actor_user_id(actor),
            action="APPLICATION_RE_EVALUATION_REQUESTED",
            target_type="application",
            target_id=application.application_id,
        )
        await self._db.commit()
        return application

    # ---- helpers -----------------------------------------------------

    async def _person_by_email(self, email: str) -> Person | None:
        """Return the Person with the given (normalized) email, or None (duplicate guard)."""
        stmt = select(Person).where(Person.email == email.strip().lower())
        return await self._db.scalar(stmt)

    async def _actor_user_id(self, actor: UserContext) -> uuid.UUID | None:
        """Resolve the actor's application_user id for audit records (best-effort)."""
        try:
            return (await self._identity._get_app_user(actor)).user_id
        except Exception:  # noqa: BLE001
            return None

    async def _candidate_email(self, application: Application) -> str:
        """Resolve the candidate's email address for an application."""
        candidate = await self._identity.get_candidate_for_application(application)
        if candidate is None:
            return ""
        person = await self._db.get(Person, candidate.person_id)
        return person.email if person else ""

    async def _manager_email(self, vacancy: Vacancy) -> str:
        """Resolve the email of the manager who posted a vacancy (its notification recipient)."""
        employee = await self._db.get(Employee, vacancy.created_by_employee_id)
        if employee is None:
            return ""
        person = await self._db.get(Person, employee.person_id)
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

    async def _get_or_create_department(self, name: str) -> Department:
        """Return the department matching `name`, creating it if it does not yet exist."""
        stmt = select(Department).where(Department.name == name.strip())
        dept = await self._db.scalar(stmt)
        if dept is not None:
            return dept
        dept = Department(name=name.strip())
        self._db.add(dept)
        await self._db.flush()
        return dept

