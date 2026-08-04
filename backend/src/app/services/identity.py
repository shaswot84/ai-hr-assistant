from __future__ import annotations

import hashlib
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.contracts.auth import UserContext
from app.domain.identity import ApplicationUser, Candidate, Employee, Person


class IdentityError(Exception):
    pass


class IdentityService:
    """Resolves a trusted UserContext into HR domain identities.

    For local dev the stub subjects are auto-provisioned: a user with
    HR_ADMIN role becomes an Employee; CANDIDATE becomes a Candidate.
    """

    def __init__(self, db: Session) -> None:
        self._db = db

    def _get_or_create_person(self, user: UserContext) -> Person:
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
        stmt = select(Candidate).where(Candidate.person_id == person.person_id)
        if self._db.scalar(stmt) is None:
            self._db.add(
                Candidate(person_id=person.person_id, registration_date=date.today())
            )
            self._db.flush()

    def _ensure_employee(self, person: Person, app_user: ApplicationUser) -> None:
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
        # Dev-stub subjects are `{role}-{email}`, so a role-based prefix collides.
        # Hash the full subject so every user gets a unique number.
        digest = hashlib.sha1(subject.encode("utf-8")).hexdigest()[:8].upper()
        return f"EMP-{digest}"

    def get_employee(self, user: UserContext) -> Employee:
        app_user = self.get_or_create_user(user)
        stmt = select(Employee).where(Employee.person_id == app_user.person_id)
        employee = self._db.scalar(stmt)
        if employee is None:
            raise IdentityError("User is not an employee.")
        return employee

    def get_candidate(self, user: UserContext) -> Candidate:
        app_user = self.get_or_create_user(user)
        stmt = select(Candidate).where(Candidate.person_id == app_user.person_id)
        candidate = self._db.scalar(stmt)
        if candidate is None:
            raise IdentityError("User is not a candidate.")
        return candidate

    def get_candidate_for_application(self, application) -> Candidate:
        stmt = select(Candidate).where(Candidate.candidate_id == application.candidate_id)
        return self._db.scalar(stmt)
