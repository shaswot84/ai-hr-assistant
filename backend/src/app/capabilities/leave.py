from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Employee, Person
from app.domain.leave import LeaveBalance, LeaveRequest, LeaveType
from app.repositories.audit import AuditRepo
from app.repositories.leave import LeaveBalanceRepo, LeaveRequestRepo, LeaveTypeRepo
from app.repositories.outbox import OutboxRepo
from app.services.identity import IdentityService
from app.shared.clock import Clock, get_clock

# A decision is only ever valid from PENDING — once approved/rejected an
# employee's request is terminal for this sprint (no re-review), mirroring
# recruitment's DECIDABLE_STATUSES so a decision can never be replayed into
# a second notification email or silently overwrite a prior outcome.
DECIDABLE_STATUSES = {"PENDING"}


class PermissionError_(Exception):
    """Raised when a caller lacks the authority to perform a leave operation."""


class LeaveService:
    """Deterministic leave-management business logic (capability layer).

    Mirrors `capabilities/recruitment.py`'s shape deliberately: same
    Clock/outbox/audit wiring, same terminal-decision guard, same
    "notify the specific responsible person, not a broadcast" approach to
    email — here that's the employee's manager (`employee.manager_employee_id`)
    instead of a vacancy's creator.
    """

    def __init__(self, db: Session, clock: Clock | None = None) -> None:
        """Bind the service to a DB session and build its repositories."""
        self._db = db
        self._clock = clock or get_clock()
        self._leave_types = LeaveTypeRepo(db)
        self._balances = LeaveBalanceRepo(db)
        self._requests = LeaveRequestRepo(db)
        self._outbox = OutboxRepo(db, clock=self._clock)
        self._audit = AuditRepo(db, clock=self._clock)
        self._identity = IdentityService(db)

    # ---- leave types (manager-configured, employee-readable) ---------

    def create_leave_type(
        self,
        actor: UserContext,
        *,
        leave_name: str,
        description: str | None,
        default_days: Decimal,
        requires_approval: bool,
        is_paid: bool,
        max_consecutive_days: int | None,
    ) -> LeaveType:
        """Create a new leave type (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can create leave types.")
        name = leave_name.strip()
        existing = self._leave_types.get_by_name_ci(name)
        if existing is not None:
            raise ValueError(
                f"A leave type named '{existing.leave_name}' already exists "
                "(names are case-insensitive)."
            )
        leave_type = LeaveType(
            leave_name=name,
            description=description,
            default_days=default_days,
            requires_approval=requires_approval,
            is_paid=is_paid,
            max_consecutive_days=max_consecutive_days,
            status="ACTIVE",
        )
        self._leave_types.create(leave_type)
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="LEAVE_TYPE_CREATED",
            target_type="leave_type",
            target_id=leave_type.leave_type_id,
            new_state={"leave_name": leave_type.leave_name},
        )
        self._db.commit()
        return leave_type

    def list_leave_types(self) -> list[LeaveType]:
        """List active leave types — every role can read these (needed to build the request form)."""
        return self._leave_types.list_active()

    # ---- balances ------------------------------------------------------

    def list_my_balance(self, actor: UserContext, year: int | None = None) -> list[dict]:
        """Return the current employee's allocated/used/remaining days per leave type."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees have a leave balance.")
        employee = self._identity.get_employee(actor)
        target_year = year or self._clock.today().year
        existing = {b.leave_type_id: b for b in self._balances.list_for_employee(employee.employee_id, target_year)}

        rows = []
        for leave_type in self._leave_types.list_active():
            balance = existing.get(leave_type.leave_type_id)
            allocated = balance.allocated_days if balance else leave_type.default_days
            used = balance.used_days if balance else Decimal(0)
            rows.append(
                {
                    "leave_type": leave_type,
                    "year": target_year,
                    "allocated_days": allocated,
                    "used_days": used,
                    "remaining_days": allocated - used,
                }
            )
        return rows

    def _get_or_create_balance(
        self, employee_id: uuid.UUID, leave_type: LeaveType, year: int
    ) -> LeaveBalance:
        """Return the employee's balance row for a type/year, creating it from the type's default on first use."""
        balance = self._balances.get(employee_id, leave_type.leave_type_id, year)
        if balance is None:
            balance = LeaveBalance(
                employee_id=employee_id,
                leave_type_id=leave_type.leave_type_id,
                year=year,
                allocated_days=leave_type.default_days,
                used_days=Decimal(0),
                updated_at=self._clock.now(),
            )
            self._balances.create(balance)
        return balance

    # ---- requests --------------------------------------------------------

    def request_leave(
        self,
        actor: UserContext,
        *,
        leave_type_id: uuid.UUID,
        start_date: date,
        end_date: date,
        reason: str | None,
    ) -> LeaveRequest:
        """Submit a leave request; validates dates, max-consecutive-days, and balance before creating it."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees can request leave.")
        employee = self._identity.get_employee(actor)
        leave_type = self._leave_types.get(leave_type_id)
        if leave_type is None or leave_type.status != "ACTIVE":
            raise ValueError("Leave type not found.")
        if end_date < start_date:
            raise ValueError("End date must be on or after the start date.")
        if start_date < self._clock.today():
            raise ValueError("Leave cannot start in the past.")

        total_days = Decimal((end_date - start_date).days + 1)
        self.check_request_conflicts(
            actor,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
        )

        year = start_date.year
        balance = self._get_or_create_balance(employee.employee_id, leave_type, year)
        remaining = balance.allocated_days - balance.used_days
        if total_days > remaining:
            raise ValueError(
                f"Not enough {leave_type.leave_name} balance: {remaining} day(s) remaining, "
                f"{total_days} requested."
            )

        now = self._clock.now()
        request_number = f"LR-{year}-{self._requests.count_for_year(year) + 1:03d}"
        request = LeaveRequest(
            request_number=request_number,
            employee_id=employee.employee_id,
            leave_type_id=leave_type_id,
            start_date=start_date,
            end_date=end_date,
            total_days=total_days,
            reason=reason,
            status="PENDING",
            version=1,
            submitted_at=now,
            updated_at=now,
        )
        self._requests.create(request)

        self._outbox.enqueue(
            "SEND_LEAVE_REQUEST_RECEIVED",
            {
                "leave_request_id": str(request.leave_request_id),
                "to_email": self._employee_email(employee),
                "subject": f"Leave request received: {request_number}",
                "body": (
                    f"Your {leave_type.leave_name} request ({start_date} to {end_date}, "
                    f"{total_days} day(s)) has been submitted and is pending approval."
                ),
            },
            aggregate_type="leave_request",
            aggregate_id=request.leave_request_id,
        )
        approver_email = self._approver_email(employee)
        if approver_email:
            self._outbox.enqueue(
                "SEND_NEW_LEAVE_REQUEST_ALERT",
                {
                    "leave_request_id": str(request.leave_request_id),
                    "to_email": approver_email,
                    "subject": f"New leave request: {request_number}",
                    "body": (
                        f"{self._employee_display_name(employee)} submitted a "
                        f"{leave_type.leave_name} request ({start_date} to {end_date}, "
                        f"{total_days} day(s)). Review it in the manager portal."
                    ),
                },
                aggregate_type="leave_request",
                aggregate_id=request.leave_request_id,
            )

        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="LEAVE_REQUEST_CREATED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            new_state={"status": "PENDING"},
        )
        self._db.commit()
        return request

    def check_request_conflicts(
        self,
        actor: UserContext,
        *,
        leave_type_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> None:
        """Reject a request that collides with the employee's live leave:
        dates already covered by an existing PENDING/APPROVED request (you
        can't apply for the same day twice), or a consecutive same-type run
        that exceeds the type's max-consecutive-days cap.

        The same checks `request_leave` runs before creating a request;
        exposed so the agent can fail fast at stage time, before asking the
        employee to confirm a submission that could not succeed. Raises
        ValueError with the same messages `request_leave` would.
        """
        employee = self._identity.get_employee(actor)
        leave_type = self._leave_types.get(leave_type_id)
        if leave_type is None or leave_type.status != "ACTIVE":
            raise ValueError("Leave type not found.")

        active_requests = self._active_requests(employee.employee_id)
        total_days = Decimal((end_date - start_date).days + 1)
        if leave_type.max_consecutive_days and total_days > leave_type.max_consecutive_days:
            raise ValueError(
                f"{leave_type.leave_name} cannot be taken for more than "
                f"{leave_type.max_consecutive_days} consecutive day(s)."
            )

        overlap = self._overlapping_request(active_requests, start_date, end_date)
        if overlap is not None:
            raise ValueError(
                f"Dates overlap your existing "
                f"{self._leave_name_of(overlap)} request "
                f"({overlap.start_date} to {overlap.end_date})."
            )

        if leave_type.max_consecutive_days:
            run_days = self._consecutive_run_days(
                [r for r in active_requests if r.leave_type_id == leave_type_id],
                start_date,
                end_date,
            )
            if run_days > leave_type.max_consecutive_days:
                raise ValueError(
                    f"{leave_type.leave_name} cannot be taken for more than "
                    f"{leave_type.max_consecutive_days} consecutive day(s) "
                    f"in one run."
                )

    def list_my_requests(self, actor: UserContext) -> list[LeaveRequest]:
        """List the current employee's own leave requests."""
        if actor.coarse_role not in ("EMPLOYEE", "HR_ADMIN"):
            raise PermissionError_("Only employees can view their own leave requests.")
        employee = self._identity.get_employee(actor)
        return self._requests.list_for_employee(employee.employee_id)

    def get_my_request(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Fetch one of the current employee's own leave requests, or raise if not theirs/not found."""
        employee = self._identity.get_employee(actor)
        request = self._requests.get_for_employee(leave_request_id, employee.employee_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return request

    def cancel_request(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Cancel one of the current employee's own still-pending requests."""
        employee = self._identity.get_employee(actor)
        request = self._requests.get_for_employee(leave_request_id, employee.employee_id)
        if request is None:
            raise ValueError("Leave request not found.")
        if request.status != "PENDING":
            raise ValueError(f"Only pending requests can be cancelled (status={request.status}).")

        now = self._clock.now()
        previous_status = request.status
        request.status = "CANCELLED"
        request.version += 1
        request.updated_at = now
        self._requests.save(request)
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="LEAVE_REQUEST_CANCELLED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            previous_state={"status": previous_status},
            new_state={"status": "CANCELLED"},
        )
        self._db.commit()
        return request

    def list_all_requests(self, actor: UserContext) -> list[LeaveRequest]:
        """List every leave request across all employees (manager-only)."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review leave requests.")
        return self._requests.list_all()

    def get_request_for_review(self, actor: UserContext, leave_request_id: uuid.UUID) -> LeaveRequest:
        """Fetch a single leave request for manager review, or raise if not found."""
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can review leave requests.")
        request = self._requests.get(leave_request_id)
        if request is None:
            raise ValueError("Leave request not found.")
        return request

    def decide_request(
        self, actor: UserContext, leave_request_id: uuid.UUID, *, approve: bool
    ) -> LeaveRequest:
        """Approve or reject a leave request; approving books the days against the employee's balance.

        Only valid from PENDING — once decided, a request is terminal for
        this sprint, so re-submitting a decision can never re-send the
        employee email, double-book the balance, or silently overwrite a
        prior outcome.
        """
        if actor.coarse_role != "HR_ADMIN":
            raise PermissionError_("Only managers can decide leave requests.")
        request = self._requests.get(leave_request_id)
        if request is None:
            raise ValueError("Leave request not found.")
        if request.status not in DECIDABLE_STATUSES:
            raise ValueError(
                f"Leave request has already been decided (status={request.status})."
            )

        decider = self._identity.get_employee(actor)
        now = self._clock.now()
        previous_status = request.status
        request.status = "APPROVED" if approve else "REJECTED"
        request.decided_by_employee_id = decider.employee_id
        request.decided_at = now
        request.version += 1
        request.updated_at = now
        self._requests.save(request)

        if approve:
            leave_type = self._leave_types.get(request.leave_type_id)
            balance = self._get_or_create_balance(
                request.employee_id, leave_type, request.start_date.year
            )
            balance.used_days = balance.used_days + request.total_days
            balance.updated_at = now
            self._balances.save(balance)

        job_type, subject, body = self._build_decision_email(request, approve=approve)
        employee = self._db.get(Employee, request.employee_id)
        self._outbox.enqueue(
            job_type,
            {
                "leave_request_id": str(request.leave_request_id),
                "to_email": self._employee_email(employee) if employee else "",
                "subject": subject,
                "body": body,
            },
            aggregate_type="leave_request",
            aggregate_id=request.leave_request_id,
        )
        self._audit.record(
            actor_user_id=self._actor_user_id(actor),
            action="LEAVE_REQUEST_APPROVED" if approve else "LEAVE_REQUEST_REJECTED",
            target_type="leave_request",
            target_id=request.leave_request_id,
            previous_state={"status": previous_status},
            new_state={"status": request.status},
        )
        self._db.commit()
        return request

    # ---- helpers -----------------------------------------------------

    def _active_requests(self, employee_id: uuid.UUID) -> list[LeaveRequest]:
        """The employee's current, live leave requests — PENDING or APPROVED,
        never CANCELLED/REJECTED/deleted (those end the run or free the days)."""
        return [
            r
            for r in self._requests.list_for_employee(employee_id)
            if r.status in ("PENDING", "APPROVED")
        ]

    def _overlapping_request(
        self, requests: list[LeaveRequest], start_date: date, end_date: date
    ) -> LeaveRequest | None:
        """Return the first request whose date range intersects [start_date, end_date]."""
        for existing in requests:
            if existing.start_date <= end_date and existing.end_date >= start_date:
                return existing
        return None

    def _consecutive_run_days(
        self, requests: list[LeaveRequest], start_date: date, end_date: date
    ) -> int:
        """Total days of the contiguous leave run this new request joins.

        Merge the existing same-type requests that are adjacent to or
        overlapping the new range (a 1-day gap breaks the run), then return
        the merged run's length. Used so applying 3+3 back-to-back days
        against a 3-day cap is caught even though no single request exceeds
        it.
        """
        runs: list[list[date]] = []
        for existing in requests:
            if (
                existing.end_date + timedelta(days=1) < start_date
                or existing.start_date - timedelta(days=1) > end_date
            ):
                continue
            runs.append([existing.start_date, existing.end_date])
        runs.append([start_date, end_date])

        merged = True
        while merged:
            merged = False
            for i in range(len(runs)):
                for j in range(i + 1, len(runs)):
                    a, b = runs[i], runs[j]
                    if (
                        a[0] <= b[1] + timedelta(days=1)
                        and b[0] <= a[1] + timedelta(days=1)
                    ):
                        runs[i] = [min(a[0], b[0]), max(a[1], b[1])]
                        runs.pop(j)
                        merged = True
                        break
                if merged:
                    break

        run = max(runs, key=lambda r: (r[1] - r[0]).days)
        return (run[1] - run[0]).days + 1

    def _leave_name_of(self, request: LeaveRequest) -> str:
        """Resolve a request's leave type name, or a generic fallback."""
        leave_type = self._leave_types.get(request.leave_type_id)
        return leave_type.leave_name if leave_type else "leave"

    def _actor_user_id(self, actor: UserContext) -> uuid.UUID | None:
        """Resolve the actor's application_user id for audit records (best-effort)."""
        try:
            return self._identity._get_app_user(actor).user_id
        except Exception:  # noqa: BLE001 - audit metadata must never block the business action
            return None

    def _employee_email(self, employee: Employee) -> str:
        """Resolve an employee's email address."""
        person = self._db.get(Person, employee.person_id)
        return person.email if person else ""

    def _employee_display_name(self, employee: Employee) -> str:
        """Resolve an employee's display name, or a generic fallback."""
        person = self._db.get(Person, employee.person_id)
        return f"{person.first_name} {person.last_name}".strip() if person else "An employee"

    def _approver_email(self, employee: Employee) -> str:
        """Resolve who should be notified of this employee's leave activity.

        Prefers the employee's own manager (`manager_employee_id`); if none
        is assigned yet (no org hierarchy configured), falls back to any
        HR_ADMIN so the notification still goes somewhere rather than being
        silently dropped — there's no manager-owns-employee scoping this
        sprint, so any HR_ADMIN can decide on any request anyway (see
        plan-recruitment.md's equivalent gap for manager-owns-vacancy).
        """
        if employee.manager_employee_id:
            manager = self._db.get(Employee, employee.manager_employee_id)
            if manager is not None:
                return self._employee_email(manager)
        stmt = select(ApplicationUser).where(ApplicationUser.coarse_role == "HR_ADMIN").limit(1)
        admin = self._db.scalar(stmt)
        if admin is None:
            return ""
        person = self._db.get(Person, admin.person_id)
        return person.email if person else ""

    def _build_decision_email(
        self, request: LeaveRequest, *, approve: bool
    ) -> tuple[str, str, str]:
        """Build the outbox job type, subject, and body for an approve/reject notification."""
        leave_type = self._leave_types.get(request.leave_type_id)
        name = leave_type.leave_name if leave_type else "leave"
        if approve:
            return (
                "SEND_LEAVE_APPROVAL_EMAIL",
                f"Leave approved: {request.request_number}",
                (
                    f"Your {name} request ({request.start_date} to {request.end_date}, "
                    f"{request.total_days} day(s)) has been approved."
                ),
            )
        return (
            "SEND_LEAVE_REJECTED",
            f"Leave request update: {request.request_number}",
            (
                f"Your {name} request ({request.start_date} to {request.end_date}) was not "
                "approved. Contact your manager for details."
            ),
        )
