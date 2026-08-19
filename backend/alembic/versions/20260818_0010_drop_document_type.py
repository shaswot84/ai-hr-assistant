"""Drop document_type column (category is the single taxonomy field).

Revision ID: 20260818_0010
Revises: 20260818_0009
Create Date: 2026-08-18

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260818_0010"
down_revision: str | None = "20260818_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("document", "document_type")


def downgrade() -> None:
    op.add_column(
        "document",
        sa.Column("document_type", sa.String(50), nullable=False, server_default="general"),
    )
