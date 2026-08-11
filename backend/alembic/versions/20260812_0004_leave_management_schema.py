"""Leave management schema (leave_type, leave_balance, leave_request)

Revision ID: 20260812_0004
Revises: 20260806_0003
Create Date: 2026-08-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260812_0004"
down_revision: Union[str, None] = "20260806_0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "leave_type",
        sa.Column("leave_type_id", sa.Uuid(), primary_key=True),
        sa.Column("leave_name", sa.String(50), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("default_days", sa.Numeric(5, 1), nullable=False),
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("is_paid", sa.Boolean(), nullable=False),
        sa.Column("max_consecutive_days", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.UniqueConstraint("leave_name"),
    )

    op.create_table(
        "leave_balance",
        sa.Column("leave_balance_id", sa.Uuid(), primary_key=True),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=False),
        sa.Column(
            "leave_type_id", sa.Uuid(), sa.ForeignKey("leave_type.leave_type_id"), nullable=False
        ),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("allocated_days", sa.Numeric(5, 1), nullable=False),
        sa.Column("used_days", sa.Numeric(5, 1), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_id", "leave_type_id", "year"),
    )
    op.create_index("ix_leave_balance_employee", "leave_balance", ["employee_id"])

    op.create_table(
        "leave_request",
        sa.Column("leave_request_id", sa.Uuid(), primary_key=True),
        sa.Column("request_number", sa.String(20), nullable=False),
        sa.Column("employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=False),
        sa.Column(
            "leave_type_id", sa.Uuid(), sa.ForeignKey("leave_type.leave_type_id"), nullable=False
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("total_days", sa.Numeric(5, 1), nullable=False),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "decided_by_employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=True
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("request_number"),
        sa.CheckConstraint("end_date >= start_date", name="ck_leave_request_dates"),
    )
    op.create_index(
        "ix_leave_request_employee_status", "leave_request", ["employee_id", "status"]
    )
    op.create_index("ix_leave_request_deleted_at", "leave_request", ["deleted_at"])


def downgrade() -> None:
    op.drop_table("leave_request")
    op.drop_table("leave_balance")
    op.drop_table("leave_type")
