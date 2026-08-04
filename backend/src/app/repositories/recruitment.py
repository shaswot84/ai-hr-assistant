from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy


class VacancyRepo:
    """Data access for vacancy rows."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def create(self, vacancy: Vacancy) -> Vacancy:
        """Persist a new vacancy and flush to obtain its generated id."""
        self._db.add(vacancy)
        self._db.flush()
        return vacancy

    def get(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        """Fetch a vacancy by id, or None if it does not exist."""
        return self._db.get(Vacancy, vacancy_id)

    def list_open(self) -> list[Vacancy]:
        """List open vacancies, newest first."""
        stmt = select(Vacancy).where(Vacancy.status == "OPEN").order_by(Vacancy.created_at.desc())
        return list(self._db.scalars(stmt))

    def list_all(self) -> list[Vacancy]:
        """List all vacancies, newest first."""
        stmt = select(Vacancy).order_by(Vacancy.created_at.desc())
        return list(self._db.scalars(stmt))

    def save(self, vacancy: Vacancy) -> None:
        """Flush pending changes to an existing vacancy row."""
        self._db.flush()


class ApplicationRepo:
    """Data access for application and evaluation rows."""

    def __init__(self, db: Session) -> None:
        """Bind the repository to a DB session."""
        self._db = db

    def create(self, application: Application) -> Application:
        """Persist a new application and flush to obtain its generated id."""
        self._db.add(application)
        self._db.flush()
        return application

    def get(self, application_id: uuid.UUID) -> Application | None:
        """Fetch an application by id, or None if it does not exist."""
        return self._db.get(Application, application_id)

    def get_for_candidate(self, application_id: uuid.UUID, candidate_id: uuid.UUID) -> Application | None:
        """Fetch an application by id but only if it belongs to the given candidate."""
        stmt = select(Application).where(
            Application.application_id == application_id,
            Application.candidate_id == candidate_id,
        )
        return self._db.scalar(stmt)

    def find_existing(self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID) -> Application | None:
        """Return the candidate's existing application for a vacancy, if any (duplicate guard)."""
        stmt = select(Application).where(
            Application.candidate_id == candidate_id,
            Application.vacancy_id == vacancy_id,
        )
        return self._db.scalar(stmt)

    def list_for_vacancy(self, vacancy_id: uuid.UUID) -> list[Application]:
        """List applications for a vacancy, most recently applied first."""
        stmt = (
            select(Application)
            .where(Application.vacancy_id == vacancy_id)
            .order_by(Application.applied_at.desc())
        )
        return list(self._db.scalars(stmt))

    def list_for_candidate(self, candidate_id: uuid.UUID) -> list[Application]:
        """List a candidate's applications, most recently applied first."""
        stmt = (
            select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.applied_at.desc())
        )
        return list(self._db.scalars(stmt))

    def save(self, application: Application) -> None:
        """Flush pending changes to an existing application row."""
        self._db.flush()

    def latest_evaluation(self, application_id: uuid.UUID) -> ApplicationEvaluation | None:
        """Return the most recent evaluation for an application, or None if none exists."""
        stmt = (
            select(ApplicationEvaluation)
            .where(ApplicationEvaluation.application_id == application_id)
            .order_by(ApplicationEvaluation.evaluated_at.desc())
            .limit(1)
        )
        return self._db.scalar(stmt)

    def add_evaluation(self, evaluation: ApplicationEvaluation) -> None:
        """Persist a new evaluation row and flush."""
        self._db.add(evaluation)
        self._db.flush()

    def count_by_status(self, vacancy_id: uuid.UUID | None = None) -> dict[str, int]:
        """Count applications grouped by status, optionally scoped to one vacancy."""
        stmt = select(Application.application_status, func.count()).group_by(
            Application.application_status
        )
        if vacancy_id is not None:
            stmt = stmt.where(Application.vacancy_id == vacancy_id)
        return {status: count for status, count in self._db.execute(stmt)}
