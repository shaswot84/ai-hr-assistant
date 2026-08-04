from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.db.base import Base

settings = get_settings()

engine = create_engine(settings.database.url, pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it afterward (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Import models so they register on Base.metadata, then create tables."""
    from app.domain import (
        identity,  # noqa: F401  (registers identity + org models)
        outbox,  # noqa: F401  (registers outbox model)
        recruitment,  # noqa: F401  (registers recruitment models)
        setting,  # noqa: F401  (registers app_setting model)
    )

    Base.metadata.create_all(bind=engine)


def verify_db_connection() -> bool:
    """Probe the database with a trivial query, returning True if reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - connectivity probe, boolean outcome
        return False
