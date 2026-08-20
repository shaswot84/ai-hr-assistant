from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, time, timezone
from typing import Any

from sqlalchemy import desc, distinct, func, or_, select, cast, String
from sqlalchemy.orm import Session

from app.domain.audit import AuditLog
from app.domain.identity import ApplicationUser, Person
from app.shared.clock import Clock, get_clock


@dataclass(frozen=True)
class EnrichedAuditLog:
    """Audit log entry enriched with resolved actor metadata."""

    audit_id: uuid.UUID
    actor_user_id: uuid.UUID | None
    actor_name: str | None
    actor_email: str | None
    actor_role: str | None
    action: str
    target_type: str | None
    target_id: uuid.UUID | None
    authorization_result: str
    previous_state: dict[str, Any] | None
    new_state: dict[str, Any] | None
    request_id: uuid.UUID | None
    created_at: datetime


class AuditRepo:
    """Read and write data access for the audit log (see `domain.audit.AuditLog`)."""

    def __init__(self, db: Session, clock: Clock | None = None) -> None:
        """Bind the repository to a DB session and (optionally) a Clock."""
        self._db = db
        self._clock = clock or get_clock()

    def record(
        self,
        *,
        actor_user_id: uuid.UUID | None,
        action: str,
        target_type: str | None = None,
        target_id: uuid.UUID | None = None,
        authorization_result: str = "ALLOW",
        previous_state: dict[str, Any] | None = None,
        new_state: dict[str, Any] | None = None,
    ) -> AuditLog:
        """Append an audit row in the current (caller-managed) transaction."""
        entry = AuditLog(
            actor_user_id=actor_user_id,
            action=action,
            target_type=target_type,
            target_id=target_id,
            authorization_result=authorization_result,
            previous_state=previous_state,
            new_state=new_state,
            created_at=self._clock.now(),
        )
        self._db.add(entry)
        self._db.flush()
        return entry

    def list_logs(
        self,
        *,
        action: str | None = None,
        target_type: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        target_id: uuid.UUID | None = None,
        authorization_result: str | None = None,
        search: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[EnrichedAuditLog], int]:
        """Query enriched audit log entries with flexible filtering and pagination."""
        stmt = (
            select(
                AuditLog,
                ApplicationUser.coarse_role,
                Person.first_name,
                Person.last_name,
                Person.email,
            )
            .outerjoin(ApplicationUser, AuditLog.actor_user_id == ApplicationUser.user_id)
            .outerjoin(Person, ApplicationUser.person_id == Person.person_id)
        )

        if action and action.strip():
            stmt = stmt.where(func.lower(AuditLog.action) == action.strip().lower())

        if target_type and target_type.strip():
            stmt = stmt.where(func.lower(AuditLog.target_type) == target_type.strip().lower())

        if actor_user_id is not None:
            stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)

        if target_id is not None:
            stmt = stmt.where(AuditLog.target_id == target_id)

        if authorization_result and authorization_result.strip():
            stmt = stmt.where(
                func.upper(AuditLog.authorization_result) == authorization_result.strip().upper()
            )

        if start_date is not None:
            stmt = stmt.where(AuditLog.created_at >= start_date)

        if end_date is not None:
            stmt = stmt.where(AuditLog.created_at <= end_date)

        if search and search.strip():
            term = f"%{search.strip()}%"
            actor_full_name = func.concat(Person.first_name, " ", Person.last_name)
            stmt = stmt.where(
                or_(
                    AuditLog.action.ilike(term),
                    AuditLog.target_type.ilike(term),
                    Person.first_name.ilike(term),
                    Person.last_name.ilike(term),
                    Person.email.ilike(term),
                    actor_full_name.ilike(term),
                    cast(AuditLog.target_id, String).ilike(term),
                    cast(AuditLog.actor_user_id, String).ilike(term),
                    cast(AuditLog.new_state, String).ilike(term),
                    cast(AuditLog.previous_state, String).ilike(term),
                )
            )

        # Count total matching rows
        count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
        total = self._db.scalar(count_stmt) or 0

        # Fetch page slice
        query = stmt.order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
        results = self._db.execute(query).all()

        items: list[EnrichedAuditLog] = []
        for log_row, role, first_name, last_name, email in results:
            actor_name: str | None = None
            if first_name or last_name:
                actor_name = f"{first_name or ''} {last_name or ''}".strip()
            elif email:
                actor_name = email

            items.append(
                EnrichedAuditLog(
                    audit_id=log_row.audit_id,
                    actor_user_id=log_row.actor_user_id,
                    actor_name=actor_name,
                    actor_email=email,
                    actor_role=role,
                    action=log_row.action,
                    target_type=log_row.target_type,
                    target_id=log_row.target_id,
                    authorization_result=log_row.authorization_result,
                    previous_state=log_row.previous_state,
                    new_state=log_row.new_state,
                    request_id=log_row.request_id,
                    created_at=log_row.created_at,
                )
            )

        return items, total

    def get_by_id(self, audit_id: uuid.UUID) -> EnrichedAuditLog | None:
        """Fetch a single enriched audit log entry by audit_id."""
        stmt = (
            select(
                AuditLog,
                ApplicationUser.coarse_role,
                Person.first_name,
                Person.last_name,
                Person.email,
            )
            .outerjoin(ApplicationUser, AuditLog.actor_user_id == ApplicationUser.user_id)
            .outerjoin(Person, ApplicationUser.person_id == Person.person_id)
            .where(AuditLog.audit_id == audit_id)
        )
        row = self._db.execute(stmt).first()
        if not row:
            return None

        log_row, role, first_name, last_name, email = row
        actor_name: str | None = None
        if first_name or last_name:
            actor_name = f"{first_name or ''} {last_name or ''}".strip()
        elif email:
            actor_name = email

        return EnrichedAuditLog(
            audit_id=log_row.audit_id,
            actor_user_id=log_row.actor_user_id,
            actor_name=actor_name,
            actor_email=email,
            actor_role=role,
            action=log_row.action,
            target_type=log_row.target_type,
            target_id=log_row.target_id,
            authorization_result=log_row.authorization_result,
            previous_state=log_row.previous_state,
            new_state=log_row.new_state,
            request_id=log_row.request_id,
            created_at=log_row.created_at,
        )

    def get_filter_options(self) -> dict[str, Any]:
        """Return distinct actions, target types, and aggregate stats."""
        # Distinct actions
        actions_stmt = select(distinct(AuditLog.action)).order_by(AuditLog.action)
        actions = [a for a in self._db.scalars(actions_stmt).all() if a]

        # Distinct target types
        targets_stmt = (
            select(distinct(AuditLog.target_type))
            .where(AuditLog.target_type.is_not(None))
            .order_by(AuditLog.target_type)
        )
        target_types = [t for t in self._db.scalars(targets_stmt).all() if t]

        # Aggregate counts
        total_stmt = select(func.count(AuditLog.audit_id))
        total_count = self._db.scalar(total_stmt) or 0

        # Today's start in current clock
        now = self._clock.now()
        start_of_today = datetime.combine(now.date(), time.min, tzinfo=now.tzinfo or timezone.utc)
        today_stmt = select(func.count(AuditLog.audit_id)).where(AuditLog.created_at >= start_of_today)
        today_count = self._db.scalar(today_stmt) or 0

        # Unique active actors
        actors_stmt = (
            select(func.count(distinct(AuditLog.actor_user_id)))
            .where(AuditLog.actor_user_id.is_not(None))
        )
        unique_actors_count = self._db.scalar(actors_stmt) or 0

        return {
            "actions": actions,
            "target_types": target_types,
            "total_count": total_count,
            "today_count": today_count,
            "unique_actors_count": unique_actors_count,
        }

