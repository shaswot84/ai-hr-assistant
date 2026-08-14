"""Durable agent workflow state (conversation_workflow_state)

Revision ID: 20260813_0008
Revises: 20260813_0007
Create Date: 2026-08-13

"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260813_0008"
down_revision: str | None = "20260813_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation_workflow_state",
        sa.Column("workflow_state_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversation.conversation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "actor_user_id",
            sa.Uuid(),
            sa.ForeignKey("application_user.user_id"),
            nullable=False,
        ),
        sa.Column("workflow_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "draft_request",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "pending_confirmation",
            sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
            nullable=True,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "uq_conversation_workflow_active",
        "conversation_workflow_state",
        ["conversation_id", "actor_user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.create_index(
        "ix_conversation_workflow_actor_status",
        "conversation_workflow_state",
        ["actor_user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversation_workflow_actor_status", table_name="conversation_workflow_state")
    op.drop_index("uq_conversation_workflow_active", table_name="conversation_workflow_state")
    op.drop_table("conversation_workflow_state")