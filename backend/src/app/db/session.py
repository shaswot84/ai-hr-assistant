"""Async engine and session factory for PostgreSQL.

The engine is built lazily, on first use, from ``DATABASE_URL`` and shared
by the whole process (FastAPI and workers). ``get_session`` yields a session
for FastAPI dependency injection.

Lazy rather than built at import time so merely importing this module never
requires a reachable/async-compatible ``DATABASE_URL`` — e.g. auth/
recruitment tests that never touch the Knowledge Service's DB layer can
still import `app.main` (which wires up the knowledge router) against a
sync-only SQLite test database.
"""

from collections.abc import AsyncGenerator
from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings


def _async_url(url: str) -> str:
    """Normalize a database URL to use an async driver (asyncpg for Postgres, aiosqlite for SQLite)."""
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "sqlite+aiosqlite:///", 1)
    if "+asyncpg" in url or "+aiosqlite" in url:
        return url
    if "+psycopg2" in url:
        return url.replace("+psycopg2", "+asyncpg")
    if "+psycopg" in url:
        return url.replace("+psycopg", "+asyncpg")
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+asyncpg://", 1)
    return url


@lru_cache
def _engine():
    settings = get_settings()
    url = _async_url(settings.database.url)
    return create_async_engine(
        url,
        echo=settings.database.echo,
        pool_pre_ping=True,  # drop stale connections after DB restarts
    )


@lru_cache
def _session_factory() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(_engine(), class_=AsyncSession, expire_on_commit=False)


def __getattr__(name: str):
    """Resolve `engine`/`async_session_factory` lazily on first access (PEP 562)."""
    if name == "engine":
        return _engine()
    if name in ("async_session_factory", "SessionLocal"):
        return _session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, closed on exit."""
    async with _session_factory()() as session:
        yield session


# Alias get_db to get_session for seamless FastAPI dependency injection
get_db = get_session


async def init_db() -> None:
    """Dev-only fallback: create any domain tables Alembic hasn't been run for."""
    from app.db.base import Base
    from app.domain import (  # noqa: F401
        audit,
        conversation,
        identity,
        leave,
        outbox,
        recruitment,
        setting,
    )

    async with _engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def verify_db_connection() -> bool:
    """Probe the database with a trivial query, returning True if reachable."""
    try:
        async with _engine().connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        return False

