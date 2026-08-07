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

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings


@lru_cache
def _engine():
    settings = get_settings()
    return create_async_engine(
        settings.database.url,
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
    if name == "async_session_factory":
        return _session_factory()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, closed on exit."""
    async with _session_factory()() as session:
        yield session
