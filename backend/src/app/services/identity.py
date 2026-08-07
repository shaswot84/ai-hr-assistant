from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Candidate, Employee
from app.domain.recruitment import Application


class IdentityError(Exception):
    """Raised when a UserContext cannot be resolved to the expected HR identity."""


class IdentityService:
    """Resolves a trusted UserContext into HR domain identities.

    Every authenticated UserContext already has a matching `application_user`
    row: JWT login only succeeds against an existing row (see `auth.jwt`), and
    demo/real accounts are provisioned by `db.seed` together with their
    Person + Employee/Candidate rows. There's no "auto-create on first sight"
    path here — that pattern belonged to the earlier Clerk/Keycloak
    self-provisioning design and is dead now that there's no external IdP.
    """

    def __init__(self, db: Session) -> None:
        """Bind the service to a DB session."""
        self._db = db

    def _get_app_user(self, user: UserContext) -> ApplicationUser:
        """Look up the ApplicationUser backing an authenticated UserContext."""
        stmt = select(ApplicationUser).where(
            ApplicationUser.identity_provider == "local",
            ApplicationUser.external_subject == user.subject,
        )
        app_user = self._db.scalar(stmt)
        if app_user is None:
            raise IdentityError("Authenticated user has no application_user record.")
        return app_user

    def get_employee(self, user: UserContext) -> Employee:
        """Resolve the user to their Employee row, raising if they are not an employee."""
        app_user = self._get_app_user(user)
        stmt = select(Employee).where(Employee.person_id == app_user.person_id)
        employee = self._db.scalar(stmt)
        if employee is None:
            raise IdentityError("User is not an employee.")
        return employee

    def get_candidate(self, user: UserContext) -> Candidate:
        """Resolve the user to their Candidate row, raising if they are not a candidate."""
        app_user = self._get_app_user(user)
        stmt = select(Candidate).where(Candidate.person_id == app_user.person_id)
        candidate = self._db.scalar(stmt)
        if candidate is None:
            raise IdentityError("User is not a candidate.")
        return candidate

    def get_candidate_for_application(self, application: Application) -> Candidate | None:
        """Return the Candidate row backing the application's candidate_id."""
        stmt = select(Candidate).where(Candidate.candidate_id == application.candidate_id)
        return self._db.scalar(stmt)
