from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.domain.audit import AuditLog
from app.shared.clock import Clock, get_clock


class AuditRepo:
    """Write-only data access for the audit log (see `domain.audit.AuditLog`)."""

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
