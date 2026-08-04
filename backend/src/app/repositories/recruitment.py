from __future__ import annotations

import uuid

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy


class VacancyRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, vacancy: Vacancy) -> Vacancy:
        self._db.add(vacancy)
        self._db.flush()
        return vacancy

    def get(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        return self._db.get(Vacancy, vacancy_id)

    def list_open(self) -> list[Vacancy]:
        stmt = select(Vacancy).where(Vacancy.status == "OPEN").order_by(Vacancy.created_at.desc())
        return list(self._db.scalars(stmt))

    def list_all(self) -> list[Vacancy]:
        stmt = select(Vacancy).order_by(Vacancy.created_at.desc())
        return list(self._db.scalars(stmt))


class ApplicationRepo:
    def __init__(self, db: Session) -> None:
        self._db = db

    def create(self, application: Application) -> Application:
        self._db.add(application)
        self._db.flush()
        return application

    def get(self, application_id: uuid.UUID) -> Application | None:
        return self._db.get(Application, application_id)

    def get_for_candidate(self, application_id: uuid.UUID, candidate_id: uuid.UUID) -> Application | None:
        stmt = select(Application).where(
            Application.application_id == application_id,
            Application.candidate_id == candidate_id,
        )
        return self._db.scalar(stmt)

    def find_existing(self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID) -> Application | None:
        stmt = select(Application).where(
            Application.candidate_id == candidate_id,
            Application.vacancy_id == vacancy_id,
        )
        return self._db.scalar(stmt)

    def list_for_vacancy(self, vacancy_id: uuid.UUID) -> list[Application]:
        stmt = (
            select(Application)
            .where(Application.vacancy_id == vacancy_id)
            .order_by(Application.applied_at.desc())
        )
        return list(self._db.scalars(stmt))

    def list_for_candidate(self, candidate_id: uuid.UUID) -> list[Application]:
        stmt = (
            select(Application)
            .where(Application.candidate_id == candidate_id)
            .order_by(Application.applied_at.desc())
        )
        return list(self._db.scalars(stmt))

    def save(self, application: Application) -> None:
        self._db.flush()

    def latest_evaluation(self, application_id: uuid.UUID) -> ApplicationEvaluation | None:
        stmt = (
            select(ApplicationEvaluation)
            .where(ApplicationEvaluation.application_id == application_id)
            .order_by(ApplicationEvaluation.evaluated_at.desc())
            .limit(1)
        )
        return self._db.scalar(stmt)

    def add_evaluation(self, evaluation: ApplicationEvaluation) -> None:
        self._db.add(evaluation)
        self._db.flush()

    def count_by_status(self, vacancy_id: uuid.UUID | None = None) -> dict[str, int]:
        stmt = select(Application.application_status, func.count()).group_by(
            Application.application_status
        )
        if vacancy_id is not None:
            stmt = stmt.where(Application.vacancy_id == vacancy_id)
        return {status: count for status, count in self._db.execute(stmt)}
