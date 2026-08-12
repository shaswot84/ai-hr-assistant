"""Add vacancy.scoring_keywords and application_evaluation.keyword_score

Revision ID: 20260813_0006
Revises: 20260812_0005
Create Date: 2026-08-13

Reintroduces a numeric score, but architecturally different from the one
dropped in 20260812_0005: that one was an LLM free-generating a 0-100
number with no rubric. This one is a fixed, auditable formula — sum of
tier weights for keywords the LLM found present in the resume, divided by
the sum of tier weights for all keywords the manager configured on the
vacancy. The manager defines the rubric (scoring_keywords) up front; the
LLM only judges keyword presence (yes/no + evidence), never the aggregate
number itself.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260813_0006"
down_revision: Union[str, None] = "20260812_0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vacancy",
        sa.Column("scoring_keywords", sa.JSON(), nullable=True),
    )
    op.add_column(
        "application_evaluation",
        sa.Column("keyword_score", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("application_evaluation", "keyword_score")
    op.drop_column("vacancy", "scoring_keywords")
