from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domain.recruitment import Application, ApplicationEvaluation, Vacancy


class VacancyRepo:
    """Data access for vacancy rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, vacancy: Vacancy) -> Vacancy:
        """Persist a new vacancy and flush to obtain its generated id."""
        self._db.add(vacancy)
        await self._db.flush()
        return vacancy

    async def get(self, vacancy_id: uuid.UUID) -> Vacancy | None:
        """Fetch a vacancy by id, or None if it does not exist (or was deleted)."""
        stmt = select(Vacancy).where(
            Vacancy.vacancy_id == vacancy_id, Vacancy.deleted_at.is_(None)
        )
        return await self._db.scalar(stmt)

    async def list_open(self) -> list[Vacancy]:
        """List open, non-deleted vacancies, newest first."""
        stmt = (
            select(Vacancy)
            .where(Vacancy.status == "OPEN", Vacancy.deleted_at.is_(None))
            .order_by(Vacancy.created_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_all(self) -> list[Vacancy]:
        """List all non-deleted vacancies, newest first."""
        stmt = (
            select(Vacancy)
            .where(Vacancy.deleted_at.is_(None))
            .order_by(Vacancy.created_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def save(self, vacancy: Vacancy) -> None:
        """Flush pending changes to an existing vacancy row."""
        await self._db.flush()


class ApplicationRepo:
    """Data access for application and evaluation rows."""

    def __init__(self, db: AsyncSession) -> None:
        """Bind the repository to an async DB session."""
        self._db = db

    async def create(self, application: Application) -> Application:
        """Persist a new application and flush to obtain its generated id."""
        self._db.add(application)
        await self._db.flush()
        return application

    async def get(self, application_id: uuid.UUID) -> Application | None:
        """Fetch an application by id, or None if it does not exist (or was deleted)."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(
                Application.application_id == application_id, Application.deleted_at.is_(None)
            )
        )
        return await self._db.scalar(stmt)

    async def get_for_candidate(self, application_id: uuid.UUID, candidate_id: uuid.UUID) -> Application | None:
        """Fetch an application by id but only if it belongs to the given candidate."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(
                Application.application_id == application_id,
                Application.candidate_id == candidate_id,
                Application.deleted_at.is_(None),
            )
        )
        return await self._db.scalar(stmt)

    async def find_existing(self, candidate_id: uuid.UUID, vacancy_id: uuid.UUID) -> Application | None:
        """Return the candidate's existing application for a vacancy, if any (duplicate guard)."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(
                Application.candidate_id == candidate_id,
                Application.vacancy_id == vacancy_id,
                Application.deleted_at.is_(None),
            )
        )
        return await self._db.scalar(stmt)

    async def list_all(self) -> list[Application]:
        """List every application across all vacancies, most recently applied first."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(Application.deleted_at.is_(None))
            .order_by(Application.applied_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_for_vacancy(self, vacancy_id: uuid.UUID) -> list[Application]:
        """List applications for a vacancy, most recently applied first."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(Application.vacancy_id == vacancy_id, Application.deleted_at.is_(None))
            .order_by(Application.applied_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def list_for_candidate(self, candidate_id: uuid.UUID) -> list[Application]:
        """List a candidate's applications, most recently applied first."""
        stmt = (
            select(Application)
            .options(selectinload(Application.vacancy))
            .where(Application.candidate_id == candidate_id, Application.deleted_at.is_(None))
            .order_by(Application.applied_at.desc())
        )
        res = await self._db.scalars(stmt)
        return list(res)

    async def save(self, application: Application) -> None:
        """Flush pending changes to an existing application row."""
        await self._db.flush()

    async def latest_evaluation(self, application_id: uuid.UUID) -> ApplicationEvaluation | None:
        """Return the most recent evaluation for an application, or None if none exists."""
        stmt = (
            select(ApplicationEvaluation)
            .where(ApplicationEvaluation.application_id == application_id)
            .order_by(ApplicationEvaluation.evaluated_at.desc())
            .limit(1)
        )
        return await self._db.scalar(stmt)

    async def add_evaluation(self, evaluation: ApplicationEvaluation) -> None:
        """Persist a new evaluation row and flush."""
        self._db.add(evaluation)
        await self._db.flush()

