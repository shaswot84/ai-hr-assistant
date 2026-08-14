"""Conversation schema (conversation, conversation_message)

Revision ID: 20260813_0007
Revises: 20260813_0006
Create Date: 2026-08-12

"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260813_0007"
down_revision: str | None = "20260813_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "conversation",
        sa.Column("conversation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("application_user.user_id"), nullable=False
        ),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_user_updated", "conversation", ["user_id", "updated_at"]
    )

    op.create_table(
        "conversation_message",
        sa.Column("message_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "conversation_id",
            sa.Uuid(),
            sa.ForeignKey("conversation.conversation_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("sequence_no", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", sa.JSON(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_conversation_message_conversation_seq",
        "conversation_message",
        ["conversation_id", "sequence_no"],
    )


def downgrade() -> None:
    op.drop_table("conversation_message")
    op.drop_table("conversation")
