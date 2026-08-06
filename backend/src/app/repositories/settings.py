from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.setting import AppSetting
from app.shared.clock import Clock, get_clock


class SettingRepo:
    """Data access for the app_setting key/value table."""

    def __init__(self, db: Session, clock: Clock | None = None) -> None:
        """Bind the repository to a DB session and (optionally) a Clock."""
        self._db = db
        self._clock = clock or get_clock()

    def get_value(self, key: str) -> str | None:
        """Return the stored value for `key`, or None if it has not been set."""
        stmt = select(AppSetting).where(AppSetting.key == key)
        setting = self._db.scalar(stmt)
        return setting.value if setting is not None else None

    def set_value(self, key: str, value: str) -> None:
        """Upsert `value` for `key` in the current (caller-managed) transaction."""
        stmt = select(AppSetting).where(AppSetting.key == key)
        setting = self._db.scalar(stmt)
        now = self._clock.now()
        if setting is None:
            self._db.add(
                AppSetting(setting_id=uuid.uuid4(), key=key, value=value, updated_at=now)
            )
        else:
            setting.value = value
            setting.updated_at = now
        self._db.flush()

    def delete(self, key: str) -> None:
        """Remove the row for `key` if it exists (restoring the default behaviour)."""
        stmt = select(AppSetting).where(AppSetting.key == key)
        setting = self._db.scalar(stmt)
        if setting is not None:
            self._db.delete(setting)
            self._db.flush()
