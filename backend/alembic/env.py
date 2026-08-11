"""Async Alembic environment.

Configures Alembic to run against the app's async SQLAlchemy engine and to
use the ORM ``Base.metadata`` as the migration target.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.config.settings import get_settings
from app.db.base import Base
import app.domain.audit  # noqa: F401  (register audit_log table)
import app.domain.identity  # noqa: F401  (register identity + org tables)
import app.domain.leave  # noqa: F401  (register leave management tables)
import app.domain.outbox  # noqa: F401  (register outbox table)
import app.domain.recruitment  # noqa: F401  (register recruitment tables)
import app.domain.setting  # noqa: F401  (register app_setting table)
import app.knowledge.models  # noqa: F401  (register knowledge/RAG tables)

config = context.config

# Wire the runtime DATABASE_URL into alembic's config if set.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

config.set_main_option("sqlalchemy.url", get_settings().database.url)

# Alembic generates migrations against the declared ORM tables.
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Generate SQL without a DB connection (``--sql`` mode)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    """Run migrations against a live connection."""
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Create an async engine from config and run migrations on it."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # No pooling: migrations create their own connection and dispose it.
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in online mode (the default)."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
