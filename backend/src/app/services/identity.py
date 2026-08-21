from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Candidate, Employee
from app.domain.recruitment import Application


class IdentityError(Exception):
    """Raised when a UserContext cannot be resolved to the expected HR identity."""


class IdentityService:
    """Resolves a trusted UserContext into HR domain identities."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the service to an async DB session."""
        self._db = db

    async def _get_app_user(self, user: UserContext) -> ApplicationUser:
        """Look up the ApplicationUser backing an authenticated UserContext."""
        stmt = select(ApplicationUser).where(
            ApplicationUser.identity_provider == "local",
            ApplicationUser.external_subject == user.subject,
        )
        app_user = await self._db.scalar(stmt)
        if app_user is None:
            raise IdentityError("Authenticated user has no application_user record.")
        return app_user

    async def get_employee(self, user: UserContext) -> Employee:
        """Resolve the user to their Employee row, raising if they are not an employee."""
        app_user = await self._get_app_user(user)
        stmt = (
            select(Employee)
            .options(selectinload(Employee.person))
            .where(Employee.person_id == app_user.person_id)
        )
        employee = await self._db.scalar(stmt)
        if employee is None:
            raise IdentityError("User is not an employee.")
        return employee

    async def get_candidate(self, user: UserContext) -> Candidate:
        """Resolve the user to their Candidate row, raising if they are not a candidate."""
        app_user = await self._get_app_user(user)
        stmt = (
            select(Candidate)
            .options(selectinload(Candidate.person))
            .where(Candidate.person_id == app_user.person_id)
        )
        candidate = await self._db.scalar(stmt)
        if candidate is None:
            raise IdentityError("User is not a candidate.")
        return candidate

    async def get_candidate_for_application(self, application: Application) -> Candidate | None:
        """Return the Candidate row backing the application's candidate_id."""
        stmt = (
            select(Candidate)
            .options(selectinload(Candidate.person))
            .where(Candidate.candidate_id == application.candidate_id)
        )
        return await self._db.scalar(stmt)


