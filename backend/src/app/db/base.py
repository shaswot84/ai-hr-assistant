"""Declarative base for all SQLAlchemy ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class every table model inherits from.

    Alembic uses ``Base.metadata`` to autogenerate migrations.
    """
