"""Company holidays table and half-day leave columns on leave_request.

Revision ID: 20260820_0011
Revises: 20260818_0010
Create Date: 2026-08-20

"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260820_0011"
down_revision: str | None = "20260818_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "company_holiday",
        sa.Column("holiday_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_recurring_yearly", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("holiday_date"),
    )
    op.create_index("ix_company_holiday_holiday_date", "company_holiday", ["holiday_date"])

    op.add_column(
        "leave_request",
        sa.Column("is_half_day", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "leave_request",
        sa.Column("half_day_period", sa.String(20), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("leave_request", "half_day_period")
    op.drop_column("leave_request", "is_half_day")
    op.drop_index("ix_company_holiday_holiday_date", table_name="company_holiday")
    op.drop_table("company_holiday")
