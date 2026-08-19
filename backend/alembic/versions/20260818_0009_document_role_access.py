"""Document role-based access (document.role_access)

Revision ID: 20260818_0009
Revises: 20260813_0008
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260818_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALL_ROLES = '["HR_ADMIN", "EMPLOYEE", "CANDIDATE", "VISITOR"]'


def upgrade() -> None:
    op.add_column(
        "document",
        sa.Column(
            "role_access",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            server_default=sa.text(f"'{_ALL_ROLES}'::jsonb"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("document", "role_access")