from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Candidate, Employee, Person


class IdentityError(Exception):
    """Raised when a UserContext cannot be resolved to the expected HR identity."""


class IdentityService:
    """Resolves a trusted UserContext into HR domain identities.

    Users are created by the seed script (`app.db.seed`) with a stored password
    hash; this service maps an authenticated UserContext to the matching
    Person/Employee/Candidate rows (creating them only if they were removed).
    """

    def __init__(self, db: Session) -> None:
        """Bind the service to a DB session."""
        self._db = db

    def _get_or_create_person(self, user: UserContext) -> Person:
        """Return the Person for the user's email, creating one from their profile if needed."""
        stmt = select(Person).where(Person.email == user.email)
        person = self._db.scalar(stmt)
        if person is not None:
            return person
        first, _, last = user.display_name.partition(" ")
        person = Person(
            first_name=first or "Test",
            last_name=last or "User",
            email=user.email,
        )
        self._db.add(person)
        self._db.flush()
        return person

    def get_or_create_user(self, user: UserContext) -> ApplicationUser:
        """Map the auth subject to an ApplicationUser, provisioning Person + role record if new."""
        stmt = select(ApplicationUser).where(ApplicationUser.external_subject == user.subject)
        app_user = self._db.scalar(stmt)
        if app_user is not None:
            return app_user
        person = self._get_or_create_person(user)
        app_user = ApplicationUser(
            external_subject=user.subject,
            person_id=person.person_id,
            coarse_role=user.coarse_role,
        )
        self._db.add(app_user)
        self._db.flush()

        if user.coarse_role == "CANDIDATE":
            self._ensure_candidate(person, app_user)
        else:
            self._ensure_employee(person, app_user)
        return app_user

    def _ensure_candidate(self, person: Person, app_user: ApplicationUser) -> None:
        """Create a Candidate row for the person if one does not yet exist."""
        stmt = select(Candidate).where(Candidate.person_id == person.person_id)
        if self._db.scalar(stmt) is None:
            self._db.add(
                Candidate(person_id=person.person_id, registration_date=date.today())
            )
            self._db.flush()

    def _ensure_employee(self, person: Person, app_user: ApplicationUser) -> None:
        """Create an Employee row for the person if one does not yet exist."""
        stmt = select(Employee).where(Employee.person_id == person.person_id)
        if self._db.scalar(stmt) is None:
            self._db.add(
                Employee(
                    person_id=person.person_id,
                    employee_number=self._employee_number(app_user.external_subject),
                )
            )
            self._db.flush()

    @staticmethod
    def _employee_number(subject: str) -> str:
        """Derive a unique, deterministic employee number from the auth subject."""
        # Hash the full subject so every user gets a unique number.
        digest = hashlib.sha1(subject.encode("utf-8")).hexdigest()[:8].upper()
        return f"EMP-{digest}"

    def get_employee(self, user: UserContext) -> Employee:
        """Resolve the user to their Employee row, raising if they are not an employee."""
        app_user = self.get_or_create_user(user)
        stmt = select(Employee).where(Employee.person_id == app_user.person_id)
        employee = self._db.scalar(stmt)
        if employee is None:
            raise IdentityError("User is not an employee.")
        return employee

    def get_candidate(self, user: UserContext) -> Candidate:
        """Resolve the user to their Candidate row, raising if they are not a candidate."""
        app_user = self.get_or_create_user(user)
        stmt = select(Candidate).where(Candidate.person_id == app_user.person_id)
        candidate = self._db.scalar(stmt)
        if candidate is None:
            raise IdentityError("User is not a candidate.")
        return candidate

    def get_candidate_for_application(self, application) -> Candidate:
        """Return the Candidate row backing the application's candidate_id."""
        stmt = select(Candidate).where(Candidate.candidate_id == application.candidate_id)
        return self._db.scalar(stmt)
