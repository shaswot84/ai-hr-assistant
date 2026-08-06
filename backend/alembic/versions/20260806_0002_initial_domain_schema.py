"""Initial domain schema (identity, recruitment, outbox, settings)

Creates the operational tables owned by the recruitment/auth stack
(person/application_user/department/candidate/employee, vacancy,
application, application_evaluation, app_setting, outbox_job). Previously
these were created imperatively via ``init_db()/create_all()``; rolling them
into Alembic makes a fresh checkout converge with ``alembic upgrade head``.

Revision ID: 20260806_0002
Revises: 20260804_0001
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260806_0002"
down_revision: Union[str, None] = "20260804_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create the domain tables in dependency order, then their indexes."""
    op.create_table(
        "person",
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("first_name", sa.String(length=100), nullable=False),
        sa.Column("last_name", sa.String(length=100), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.PrimaryKeyConstraint("person_id"),
    )
    op.create_index("ix_person_email", "person", ["email"], unique=True)

    op.create_table(
        "department",
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.PrimaryKeyConstraint("department_id"),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "application_user",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("external_subject", sa.String(length=255), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("coarse_role", sa.String(length=30), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["person.person_id"]),
        sa.PrimaryKeyConstraint("user_id"),
    )
    op.create_index(
        "ix_application_user_external_subject",
        "application_user",
        ["external_subject"],
        unique=True,
    )

    op.create_table(
        "candidate",
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["person.person_id"]),
        sa.PrimaryKeyConstraint("candidate_id"),
        sa.UniqueConstraint("person_id"),
    )

    op.create_table(
        "employee",
        sa.Column("employee_id", sa.Uuid(), nullable=False),
        sa.Column("person_id", sa.Uuid(), nullable=False),
        sa.Column("employee_number", sa.String(length=30), nullable=False),
        sa.ForeignKeyConstraint(["person_id"], ["person.person_id"]),
        sa.PrimaryKeyConstraint("employee_id"),
        sa.UniqueConstraint("person_id"),
        sa.UniqueConstraint("employee_number"),
    )

    op.create_table(
        "vacancy",
        sa.Column("vacancy_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.String(length=150), nullable=False),
        sa.Column("department_id", sa.Uuid(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("employment_type", sa.String(length=30), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=True),
        sa.Column("closing_date", sa.Date(), nullable=True),
        sa.Column("created_by_employee_id", sa.Uuid(), nullable=False),
        sa.Column("approval_status", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["department_id"], ["department.department_id"]),
        sa.ForeignKeyConstraint(["created_by_employee_id"], ["employee.employee_id"]),
        sa.PrimaryKeyConstraint("vacancy_id"),
    )

    op.create_table(
        "application",
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("candidate_id", sa.Uuid(), nullable=False),
        sa.Column("vacancy_id", sa.Uuid(), nullable=False),
        sa.Column("cv_object_key", sa.String(length=500), nullable=True),
        sa.Column("application_status", sa.String(length=30), nullable=False),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["candidate_id"], ["candidate.candidate_id"]),
        sa.ForeignKeyConstraint(["vacancy_id"], ["vacancy.vacancy_id"]),
        sa.PrimaryKeyConstraint("application_id"),
        sa.UniqueConstraint("candidate_id", "vacancy_id"),
    )
    op.create_index("ix_application_candidate", "application", ["candidate_id"])
    op.create_index("ix_application_vacancy", "application", ["vacancy_id"])

    op.create_table(
        "application_evaluation",
        sa.Column("evaluation_id", sa.Uuid(), nullable=False),
        sa.Column("application_id", sa.Uuid(), nullable=False),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(length=100), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["application_id"], ["application.application_id"]),
        sa.PrimaryKeyConstraint("evaluation_id"),
    )
    op.create_index(
        "ix_application_evaluation_application_id",
        "application_evaluation",
        ["application_id"],
    )

    op.create_table(
        "app_setting",
        sa.Column("setting_id", sa.Uuid(), nullable=False),
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("setting_id"),
    )
    op.create_index("ix_app_setting_key", "app_setting", ["key"], unique=True)

    op.create_table(
        "outbox_job",
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("job_type", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("job_id"),
    )


def downgrade() -> None:
    """Drop tables and indexes in reverse dependency order."""
    op.drop_table("outbox_job")
    op.drop_index("ix_app_setting_key", table_name="app_setting")
    op.drop_table("app_setting")
    op.drop_index(
        "ix_application_evaluation_application_id",
        table_name="application_evaluation",
    )
    op.drop_table("application_evaluation")
    op.drop_index("ix_application_vacancy", table_name="application")
    op.drop_index("ix_application_candidate", table_name="application")
    op.drop_table("application")
    op.drop_table("vacancy")
    op.drop_table("employee")
    op.drop_table("candidate")
    op.drop_index("ix_application_user_external_subject", table_name="application_user")
    op.drop_table("application_user")
    op.drop_table("department")
    op.drop_index("ix_person_email", table_name="person")
    op.drop_table("person")
