"""Sync engine and session factory for the recruitment/auth/domain tables.

`develop`'s `db/session.py` is async (asyncpg) and is the Knowledge Service's
engine. The recruitment/auth stack has no need for an async DB driver, so it
runs on a plain sync SQLAlchemy engine instead of forcing everything through
asyncio. Both engines point at the same Postgres instance and share the same
`Base.metadata` (see `app.db.base`), so tables created/migrated by either
stack are visible to both. The sync URL is derived from the single
`DATABASE_URL` setting rather than introducing a second env var.
"""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.config.settings import get_settings
from app.db.base import Base

settings = get_settings()


def _sync_url(url: str) -> str:
    """Swap an async driver for its sync psycopg2 equivalent, if present."""
    if "+asyncpg" in url:
        return url.replace("+asyncpg", "+psycopg2")
    if "+psycopg2" in url or "+psycopg" in url:
        return url
    return url.replace("postgresql://", "postgresql+psycopg2://", 1)


engine = create_engine(_sync_url(settings.database.url), pool_pre_ping=True)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and always close it afterward (FastAPI dependency)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db() -> None:
    """Dev-only fallback: create any domain tables Alembic hasn't been run for.

    `make migrate` (Alembic) is the real schema-management path (HLD
    principle #14) — this only exists so a local run without Docker/Alembic
    still has usable tables. It's idempotent and a no-op once migrations
    have already created the tables.
    """
    from app.domain import audit, identity, outbox, recruitment, setting  # noqa: F401

    Base.metadata.create_all(bind=engine)


def verify_db_connection() -> bool:
    """Probe the database with a trivial query, returning True if reachable."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001 - connectivity probe, boolean outcome
        return False
