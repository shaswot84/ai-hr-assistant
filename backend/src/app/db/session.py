"""Async engine and session factory for PostgreSQL.

The engine is created once at import time from ``DATABASE_URL`` and shared
by the whole process (FastAPI and workers). ``get_session`` yields a session
for FastAPI dependency injection.
"""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config.settings import get_settings

_settings = get_settings()

engine = create_async_engine(
    _settings.database.url,
    echo=_settings.database.echo,
    pool_pre_ping=True,  # drop stale connections after DB restarts
)

async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # keep attributes usable after commit
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: one session per request, closed on exit."""
    async with async_session_factory() as session:
        yield session
