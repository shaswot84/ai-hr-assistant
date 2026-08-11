"""People (org directory) capability layer.

Deterministic business logic for the HR-side org spine: departments,
designations, employees, and the candidate → employee hire handoff.

Authorization (WHO may act), validation (WHAT is legal), and audit (WHAT
changed) live here, never in the route layer — mirroring
`capabilities/recruitment.py`. The route layer only maps exceptions to HTTP
statuses.

Error contract (documented on the route layer too):
- `PermissionError_`  → 403  caller lacks authority
- `NotFoundError_`    → 404  referenced record does not exist
- `ConflictError_`    → 409  uniqueness/state invariant violation
- `ValueError`        → 422  malformed input value
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.passwords import hash_password
from app.contracts.auth import UserContext
from app.domain.identity import (
    ApplicationUser,
    Candidate,
    Department,
    Designation,
    Employee,
    Person,
)
from app.repositories.audit import AuditRepo
from app.repositories.outbox import OutboxRepo
from app.repositories.people import DepartmentRepo, DesignationRepo, EmployeeRepo
from app.repositories.recruitment import ApplicationRepo
from app.services.identity import IdentityService
from app.shared.clock import Clock, get_clock

# Employment lifecycle states for the Employee row (String(20) on the model).
EMPLOYMENT_ACTIVE = "ACTIVE"
EMPLOYMENT_INACTIVE = "INACTIVE"
VALID_EMPLOYMENT_STATUSES = {EMPLOYMENT_ACTIVE, EMPLOYMENT_INACTIVE}

# Coarse roles used when provisioning/upgrading login accounts.
ROLE_HR_ADMIN = "HR_ADMIN"
ROLE_EMPLOYEE = "EMPLOYEE"

# Only shortlisted applications may be converted into hires: APPLIED is still
# under review, REJECTED is terminal. Keeps the hire handoff aligned with the
# recruitment decision flow (see capabilities/recruitment.py).
HIREABLE_APPLICATION_STATUS = "SHORTLISTED"


class PermissionError_(Exception):
    """Raised when a caller lacks the authority to perform a people operation."""


class NotFoundError_(Exception):
    """Raised when a referenced record (employee/dept/designation/application) does not exist."""


class ConflictError_(Exception):
    """Raised when an operation would violate a uniqueness or state invariant."""


class PeopleService:
    """Org directory + hire handoff business logic (capability layer)."""

    def __init__(self, db: Session, clock: Clock | None = None) -> None:
        """Bind the service to a DB session and build its repositories."""
        self._db = db
        self._clock = clock or get_clock()
        self._departments = DepartmentRepo(db)
        self._designations = DesignationRepo(db)
        self._employees = EmployeeRepo(db)
        self._applications = ApplicationRepo(db)
        self._outbox = OutboxRepo(db, clock=self._clock)
        self._audit = AuditRepo(db, clock=self._clock)
        self._identity = IdentityService(db)

    # ---- departments ---------------------------------------------------

    def list_departments(self) -> list[Department]:
        """List all departments alphabetically."""
        return self._departments.list_all()

    def create_department(self, actor: UserContext, *, name: str) -> Department:
        """Create a department (HR_ADMIN only); rejects duplicate names."""
        self._require_hr_admin(actor)
        if self._departments.get_by_name(name) is not None:
            raise ConflictError_(f"Department {name!r} already exists.")
        department = self._departments.create(Department(name=name.strip()))
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="DEPARTMENT_CREATED",
            target_type="department",
            target_id=department.department_id,
            new_state={"name": department.name},
        )
        self._db.commit()
        return department

    # ---- designations --------------------------------------------------

    def list_designations(self, *, department_id: uuid.UUID | None = None) -> list[Designation]:
        """List designations, optionally filtered to one department."""
        if department_id is not None:
            self._require_department(department_id)
            return self._designations.list_for_department(department_id)
        return self._designations.list_all()

    def create_designation(
        self,
        actor: UserContext,
        *,
        department_id: uuid.UUID,
        title: str,
        level: int | None = None,
    ) -> Designation:
        """Create a designation in a department (HR_ADMIN only)."""
        self._require_hr_admin(actor)
        department = self._require_department(department_id)
        if self._designations.get_by_department_title(department_id, title) is not None:
            raise ConflictError_(f"Designation {title!r} already exists in this department.")
        designation = self._designations.create(
            Designation(department_id=department.department_id, title=title.strip(), level=level)
        )
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="DESIGNATION_CREATED",
            target_type="designation",
            target_id=designation.designation_id,
            new_state={"title": designation.title, "level": designation.level},
        )
        self._db.commit()
        return designation

    # ---- employees -----------------------------------------------------

    def list_employees(
        self,
        *,
        search: str | None = None,
        department_id: uuid.UUID | None = None,
        employment_status: str | None = None,
    ) -> list[Employee]:
        """List employees with optional search/filters."""
        if employment_status is not None and employment_status not in VALID_EMPLOYMENT_STATUSES:
            raise ValueError(
                f"Invalid employment_status {employment_status!r}; expected one of "
                f"{sorted(VALID_EMPLOYMENT_STATUSES)}."
            )
        return self._employees.list(
            search=search,
            department_id=department_id,
            employment_status=employment_status,
        )

    def get_employee(self, actor: UserContext, employee_id: uuid.UUID) -> Employee:
        """Fetch one employee. HR_ADMIN may view anyone; EMPLOYEE only themselves."""
        employee = self._employees.get(employee_id)
        if employee is None:
            raise NotFoundError_("Employee not found.")
        if actor.coarse_role != ROLE_HR_ADMIN:
            if actor.coarse_role != ROLE_EMPLOYEE:
                raise PermissionError_("Only HR administrators or the employee themselves can view a profile.")
            own = self._identity.get_employee(actor)
            if own.person_id != employee.person_id:
                raise PermissionError_("Employees can only view their own profile.")
        return employee

    def my_profile(self, actor: UserContext) -> Employee:
        """Return the current user's own employee profile (self-service)."""
        return self._identity.get_employee(actor)

    def create_employee(
        self,
        actor: UserContext,
        *,
        first_name: str,
        last_name: str,
        email: str,
        phone: str | None,
        employee_code: str,
        department_id: uuid.UUID,
        designation_id: uuid.UUID,
        manager_employee_id: uuid.UUID | None,
        joining_date,
        password: str,
    ) -> Employee:
        """Create an employee with HR-provided login credentials (HR_ADMIN only).

        Provisions the Person + ApplicationUser (EMPLOYEE role, hashed
        password) + Employee rows atomically in one transaction — a failure
        anywhere rolls all of them back, so no half-created account exists.
        """
        self._require_hr_admin(actor)
        # Referential integrity: department/designation/manager must exist and
        # the manager must be an active employee.
        self._require_department(department_id)
        self._require_designation(designation_id)
        if manager_employee_id is not None:
            self._require_active_manager(manager_employee_id)
        # Uniqueness: one email per Person, one code per Employee. Emails are
        # normalized to lowercase to match the auth layer's login lookup.
        if self._person_by_email(email) is not None:
            raise ConflictError_("A person with this email already exists.")
        if self._employees.get_by_code(employee_code) is not None:
            raise ConflictError_("An employee with this code already exists.")

        now = self._clock.now()
        person = Person(
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            email=email.strip().lower(),
            phone=phone.strip() if phone else None,
            created_at=now,
            updated_at=now,
        )
        self._db.add(person)
        self._db.flush()

        # HR provides the credentials; subject is a fresh local uuid (matches
        # the seed convention in db/seed.py).
        self._db.add(
            ApplicationUser(
                external_subject=str(uuid.uuid4()),
                person_id=person.person_id,
                coarse_role=ROLE_EMPLOYEE,
                password_hash=hash_password(password),
                created_at=now,
                updated_at=now,
            )
        )
        self._db.flush()

        employee = self._employees.create(
            Employee(
                person_id=person.person_id,
                employee_code=employee_code.strip(),
                department_id=department_id,
                designation_id=designation_id,
                manager_employee_id=manager_employee_id,
                joining_date=joining_date,
                employment_status=EMPLOYMENT_ACTIVE,
                created_at=now,
                updated_at=now,
            )
        )
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="EMPLOYEE_CREATED",
            target_type="employee",
            target_id=employee.employee_id,
            new_state={
                "employee_code": employee.employee_code,
                "department_id": str(department_id),
                "designation_id": str(designation_id),
                "employment_status": EMPLOYMENT_ACTIVE,
            },
        )
        self._db.commit()
        return employee

    def update_employee(
        self,
        actor: UserContext,
        employee_id: uuid.UUID,
        *,
        first_name: str | None = None,
        last_name: str | None = None,
        phone: str | None = None,
        department_id: uuid.UUID | None = None,
        designation_id: uuid.UUID | None = None,
        manager_employee_id: uuid.UUID | None = None,
        joining_date=None,
        employment_status: str | None = None,
    ) -> Employee:
        """Update profile fields of an employee (HR_ADMIN only).

        Patch semantics: only non-`None` fields are applied by the caller
        (the route uses `exclude_unset`), so explicitly passing
        `manager_employee_id=None` clears the manager link. Status changes to
        INACTIVE also revoke the user's login atomically (same transaction).
        """
        self._require_hr_admin(actor)
        employee = self._employees.get(employee_id)
        if employee is None:
            raise NotFoundError_("Employee not found.")
        person = employee.person
        previous = {
            "employment_status": employee.employment_status,
            "manager_employee_id": str(employee.manager_employee_id) if employee.manager_employee_id else None,
        }

        # Apply the patch (field-by-field; None means "not sent" for scalars).
        if first_name is not None:
            person.first_name = first_name.strip()
        if last_name is not None:
            person.last_name = last_name.strip()
        if phone is not None:
            person.phone = phone.strip() or None
        if department_id is not None:
            self._require_department(department_id)
            employee.department_id = department_id
        if designation_id is not None:
            self._require_designation(designation_id)
            employee.designation_id = designation_id
        if manager_employee_id is not None:
            self._require_active_manager(manager_employee_id)
            employee.manager_employee_id = manager_employee_id
        if joining_date is not None:
            employee.joining_date = joining_date
        if employment_status is not None:
            if employment_status not in VALID_EMPLOYMENT_STATUSES:
                raise ValueError(
                    f"Invalid employment_status {employment_status!r}; expected one of "
                    f"{sorted(VALID_EMPLOYMENT_STATUSES)}."
                )
            employee.employment_status = employment_status
            self._sync_login_status(employee.person_id, active=employment_status == EMPLOYMENT_ACTIVE)

        person.updated_at = self._clock.now()
        employee.updated_at = person.updated_at
        self._employees.save(employee)
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="EMPLOYEE_UPDATED",
            target_type="employee",
            target_id=employee.employee_id,
            previous_state=previous,
            new_state={
                "employment_status": employee.employment_status,
                "manager_employee_id": str(employee.manager_employee_id) if employee.manager_employee_id else None,
            },
        )
        self._db.commit()
        return employee

    def deactivate_employee(self, actor: UserContext, employee_id: uuid.UUID) -> Employee:
        """Deactivate an employee (HR_ADMIN only).

        Atomic by design: `Employee.employment_status` and the matching
        `ApplicationUser.status` flip in the same transaction, so a
        deactivated employee can no longer authenticate. Blocked while the
        employee still manages active reports (a dangling manager link would
        otherwise be left behind).
        """
        self._require_hr_admin(actor)
        employee = self._employees.get(employee_id)
        if employee is None:
            raise NotFoundError_("Employee not found.")
        if employee.employment_status == EMPLOYMENT_INACTIVE:
            raise ConflictError_("Employee is already inactive.")
        if self._count_active_reports(employee.employee_id) > 0:
            raise ConflictError_(
                "Employee still manages active reports; reassign them before deactivating."
            )

        previous_status = employee.employment_status
        employee.employment_status = EMPLOYMENT_INACTIVE
        employee.updated_at = self._clock.now()
        # Revoke login access in the same transaction (single-role accounts).
        self._sync_login_status(employee.person_id, active=False)
        self._employees.save(employee)
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="EMPLOYEE_DEACTIVATED",
            target_type="employee",
            target_id=employee.employee_id,
            previous_state={"employment_status": previous_status},
            new_state={"employment_status": EMPLOYMENT_INACTIVE},
        )
        self._db.commit()
        return employee

    # ---- hire handoff --------------------------------------------------

    def hire_candidate(
        self,
        actor: UserContext,
        application_id: uuid.UUID,
        *,
        employee_code: str,
        department_id: uuid.UUID,
        designation_id: uuid.UUID,
        manager_employee_id: uuid.UUID | None,
        joining_date,
    ) -> Employee:
        """Hire a shortlisted candidate from their application (HR_ADMIN only).

        Converts the candidate into an employee on their existing Person row,
        links the Candidate record (`hired_employee_id` / `hired_at` /
        `HIRED`), and flips the user's coarse role to EMPLOYEE so they can
        sign into the employee portal (single-role model). All of this is one
        transaction; the candidate's application history stays in the DB.
        """
        self._require_hr_admin(actor)
        self._require_department(department_id)
        self._require_designation(designation_id)
        if manager_employee_id is not None:
            self._require_active_manager(manager_employee_id)
        if self._employees.get_by_code(employee_code) is not None:
            raise ConflictError_("An employee with this code already exists.")

        application = self._applications.get(application_id)
        if application is None:
            raise NotFoundError_("Application not found.")
        if application.application_status != HIREABLE_APPLICATION_STATUS:
            raise ConflictError_(
                f"Only {HIREABLE_APPLICATION_STATUS} applications can be hired "
                f"(current status: {application.application_status})."
            )
        candidate = self._identity.get_candidate_for_application(application)
        if candidate is None:
            raise NotFoundError_("Candidate not found for application.")
        if candidate.hired_employee_id is not None:
            raise ConflictError_("This candidate has already been hired.")
        if self._employees.find_by_person_id(candidate.person_id) is not None:
            raise ConflictError_("This person is already an employee.")

        now = self._clock.now()
        employee = self._employees.create(
            Employee(
                person_id=candidate.person_id,
                employee_code=employee_code.strip(),
                department_id=department_id,
                designation_id=designation_id,
                manager_employee_id=manager_employee_id,
                joining_date=joining_date,
                employment_status=EMPLOYMENT_ACTIVE,
                created_at=now,
                updated_at=now,
            )
        )
        # Link the candidate to their new employee record and mark them hired.
        candidate.hired_employee_id = employee.employee_id
        candidate.hired_at = now
        candidate.candidate_status = "HIRED"
        candidate.updated_at = now
        # Upgrade the existing account to the employee role (not a second
        # account) so the hiree can access the employee portal.
        app_user = self._app_user_for_person(candidate.person_id)
        if app_user is not None:
            app_user.coarse_role = ROLE_EMPLOYEE
            app_user.updated_at = now

        # Close out the candidate's other open applications in the same
        # transaction: once hired, an applicant shouldn't stay shortlisted or
        # under review elsewhere. Each withdrawal gets a notification email
        # via the outbox — all-or-nothing with the hire itself.
        self._withdraw_other_applications(
            candidate.candidate_id,
            hired_application_id=application_id,
            candidate_email=self._candidate_email(candidate),
            now=now,
        )

        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="CANDIDATE_HIRED",
            target_type="candidate",
            target_id=candidate.candidate_id,
            new_state={
                "employee_id": str(employee.employee_id),
                "application_id": str(application_id),
                "department_id": str(department_id),
                "designation_id": str(designation_id),
            },
        )
        self._db.commit()
        return employee

    # ---- private helpers ----------------------------------------------

    def _require_hr_admin(self, actor: UserContext) -> None:
        """Raise PermissionError_ unless the actor holds the HR_ADMIN role."""
        if actor.coarse_role != ROLE_HR_ADMIN:
            raise PermissionError_("Only HR administrators can manage people.")

    def _require_department(self, department_id: uuid.UUID) -> Department:
        """Return the department, raising NotFoundError_ if it does not exist."""
        department = self._departments.get(department_id)
        if department is None:
            raise NotFoundError_("Department not found.")
        return department

    def _require_designation(self, designation_id: uuid.UUID) -> Designation:
        """Return the designation, raising NotFoundError_ if it does not exist."""
        designation = self._designations.get(designation_id)
        if designation is None:
            raise NotFoundError_("Designation not found.")
        return designation

    def _require_active_manager(self, manager_employee_id: uuid.UUID) -> Employee:
        """Return the manager, validating they exist and are an active employee."""
        manager = self._employees.get(manager_employee_id)
        if manager is None:
            raise NotFoundError_("Manager not found.")
        if manager.employment_status != EMPLOYMENT_ACTIVE:
            raise ConflictError_("Manager must be an active employee.")
        return manager

    def _person_by_email(self, email: str) -> Person | None:
        """Return the Person with the given email, or None (uniqueness guard)."""
        stmt = select(Person).where(Person.email == email.strip().lower())
        return self._db.scalar(stmt)

    def _app_user_for_person(self, person_id: uuid.UUID) -> ApplicationUser | None:
        """Return the local ApplicationUser for a person, or None if they have none."""
        stmt = select(ApplicationUser).where(
            ApplicationUser.identity_provider == "local",
            ApplicationUser.person_id == person_id,
        )
        return self._db.scalar(stmt)

    def _sync_login_status(self, person_id: uuid.UUID, *, active: bool) -> None:
        """Flip the user's login status to match their employment status (same tx)."""
        app_user = self._app_user_for_person(person_id)
        if app_user is not None:
            app_user.status = "ACTIVE" if active else "INACTIVE"

    def _count_active_reports(self, manager_employee_id: uuid.UUID) -> int:
        """Count active employees who report directly to the given manager."""
        stmt = (
            select(func.count())
            .select_from(Employee)
            .where(
                Employee.manager_employee_id == manager_employee_id,
                Employee.employment_status == EMPLOYMENT_ACTIVE,
            )
        )
        return int(self._db.scalar(stmt) or 0)

    def _candidate_email(self, candidate: Candidate) -> str:
        """Resolve the candidate's email for notifications ('' if the Person is missing)."""
        person = self._db.get(Person, candidate.person_id)
        return person.email if person else ""

    def _withdraw_other_applications(
        self,
        candidate_id: uuid.UUID,
        *,
        hired_application_id: uuid.UUID,
        candidate_email: str,
        now,
    ) -> None:
        """Withdraw the candidate's remaining open applications after hiring.

        Open = APPLIED or SHORTLISTED (REJECTED/WITHDRAWN are already
        terminal). Each withdrawal is written in the current transaction and
        enqueues a ``SEND_APPLICATION_WITHDRAWN`` notification email via the
        outbox, so the email is only sent if the whole hire commits.
        """
        open_statuses = {"APPLIED", "SHORTLISTED"}
        for application in self._applications.list_for_candidate(candidate_id):
            if application.application_id == hired_application_id:
                continue
            if application.application_status not in open_statuses:
                continue
            vacancy_title = application.vacancy.title if application.vacancy else "the position"
            application.application_status = "WITHDRAWN"
            application.withdrawn_at = now
            application.updated_at = now
            self._outbox.enqueue(
                "SEND_APPLICATION_WITHDRAWN",
                {
                    "application_id": str(application.application_id),
                    "to_email": candidate_email,
                    "subject": f"Application update: {vacancy_title}",
                    "body": (
                        f"Thank you for your application to {vacancy_title}. Since you've "
                        "accepted a position with Summit Technologies, this application has "
                        "been withdrawn. We appreciate your interest and wish you the best."
                    ),
                },
                aggregate_type="application",
                aggregate_id=application.application_id,
            )

    def _actor_user_id(self, actor: UserContext) -> uuid.UUID | None:
        """Resolve the actor's application_user id for audit records (best-effort)."""
        try:
            return self._identity._get_app_user(actor).user_id
        except Exception:  # noqa: BLE001 - audit metadata must never block the business action
            return None
