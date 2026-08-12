"""Drop application_evaluation.score, add failed flag

Revision ID: 20260812_0005
Revises: 20260812_0004
Create Date: 2026-08-12

The AI screening's headline 0-100 "match score" was a single number the
LLM free-generated with no rubric or calibration behind it — not derived
from the score_factors it also produced, so two candidates scored 92 and
89 carried no real, comparable difference. Removed in favor of the
requirements gate + categorical recommendation, which are the signals an
LLM can actually support honestly.

`failed` distinguishes a screening that genuinely couldn't run (AI
provider unavailable) from a normal result, so the UI can show a clear
error + retry action instead of a fabricated score.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260812_0005"
down_revision: Union[str, None] = "20260812_0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column("application_evaluation", "score")
    op.add_column(
        "application_evaluation",
        sa.Column("failed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("application_evaluation", "failed")
    op.add_column(
        "application_evaluation",
        sa.Column("score", sa.Integer(), nullable=True),
    )
