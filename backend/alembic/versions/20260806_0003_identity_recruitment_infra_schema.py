"""Identity/org + recruitment + infra schema (auth + recruitment module)

Revision ID: 20260806_0003
Revises: 20260804_0001
Create Date: 2026-08-06

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "20260806_0003"
down_revision: Union[str, None] = "20260804_0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "person",
        sa.Column("person_id", sa.Uuid(), primary_key=True),
        sa.Column("first_name", sa.String(100), nullable=False),
        sa.Column("last_name", sa.String(100), nullable=False),
        sa.Column("email", sa.String(150), nullable=False),
        sa.Column("phone", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_person_email", "person", ["email"])

    op.create_table(
        "department",
        sa.Column("department_id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.UniqueConstraint("name"),
    )

    op.create_table(
        "designation",
        sa.Column("designation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("department.department_id"), nullable=False
        ),
        sa.Column("title", sa.String(100), nullable=False),
        sa.Column("level", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("department_id", "title"),
    )

    op.create_table(
        "application_user",
        sa.Column("user_id", sa.Uuid(), primary_key=True),
        sa.Column("person_id", sa.Uuid(), sa.ForeignKey("person.person_id"), nullable=False),
        sa.Column("identity_provider", sa.String(50), nullable=False, server_default="local"),
        sa.Column("external_subject", sa.String(255), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("coarse_role", sa.String(30), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("identity_provider", "external_subject"),
    )
    op.create_index("ix_application_user_external_subject", "application_user", ["external_subject"])

    op.create_table(
        "employee",
        sa.Column("employee_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "person_id", sa.Uuid(), sa.ForeignKey("person.person_id"), nullable=False, unique=True
        ),
        sa.Column("employee_code", sa.String(30), nullable=False),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("department.department_id"), nullable=False
        ),
        sa.Column(
            "designation_id", sa.Uuid(), sa.ForeignKey("designation.designation_id"), nullable=False
        ),
        sa.Column(
            "manager_employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=True
        ),
        sa.Column("joining_date", sa.Date(), nullable=False),
        sa.Column("employment_status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("employee_code"),
    )
    op.create_index("ix_employee_manager_employee_id", "employee", ["manager_employee_id"])

    op.create_table(
        "candidate",
        sa.Column("candidate_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "person_id", sa.Uuid(), sa.ForeignKey("person.person_id"), nullable=False, unique=True
        ),
        sa.Column("registration_date", sa.Date(), nullable=False),
        sa.Column("candidate_status", sa.String(30), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "hired_employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=True
        ),
        sa.Column("hired_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_candidate_deleted_at", "candidate", ["deleted_at"])

    op.create_table(
        "vacancy",
        sa.Column("vacancy_id", sa.Uuid(), primary_key=True),
        sa.Column("title", sa.String(150), nullable=False),
        sa.Column(
            "department_id", sa.Uuid(), sa.ForeignKey("department.department_id"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("employment_type", sa.String(30), nullable=False),
        sa.Column("opening_date", sa.Date(), nullable=True),
        sa.Column("closing_date", sa.Date(), nullable=True),
        sa.Column(
            "created_by_employee_id", sa.Uuid(), sa.ForeignKey("employee.employee_id"), nullable=False
        ),
        sa.Column("approval_status", sa.String(20), nullable=False, server_default="APPROVED"),
        sa.Column("status", sa.String(30), nullable=False, server_default="OPEN"),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_vacancy_deleted_at", "vacancy", ["deleted_at"])

    op.create_table(
        "application",
        sa.Column("application_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "candidate_id", sa.Uuid(), sa.ForeignKey("candidate.candidate_id"), nullable=False
        ),
        sa.Column("vacancy_id", sa.Uuid(), sa.ForeignKey("vacancy.vacancy_id"), nullable=False),
        sa.Column("cv_object_key", sa.String(500), nullable=True),
        sa.Column("application_status", sa.String(30), nullable=False, server_default="APPLIED"),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "vacancy_id"),
    )
    op.create_index("ix_application_candidate", "application", ["candidate_id"])
    op.create_index("ix_application_vacancy_status", "application", ["vacancy_id", "application_status"])
    op.create_index("ix_application_deleted_at", "application", ["deleted_at"])

    op.create_table(
        "application_evaluation",
        sa.Column("evaluation_id", sa.Uuid(), primary_key=True),
        sa.Column(
            "application_id",
            sa.Uuid(),
            sa.ForeignKey("application.application_id"),
            nullable=False,
        ),
        sa.Column("score", sa.Integer(), nullable=False),
        sa.Column("overview", sa.Text(), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("prompt_version", sa.String(50), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_application_evaluation_application_id", "application_evaluation", ["application_id"]
    )

    op.create_table(
        "outbox_job",
        sa.Column("job_id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.String(100), nullable=False),
        sa.Column("aggregate_type", sa.String(50), nullable=True),
        sa.Column("aggregate_id", sa.Uuid(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_error", sa.String(1000), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index("ix_outbox_status_available", "outbox_job", ["status", "available_at"])

    op.create_table(
        "app_setting",
        sa.Column("setting_id", sa.Uuid(), primary_key=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("key"),
    )
    op.create_index("ix_app_setting_key", "app_setting", ["key"])

    op.create_table(
        "audit_log",
        sa.Column("audit_id", sa.Uuid(), primary_key=True),
        sa.Column("actor_user_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("target_type", sa.String(50), nullable=True),
        sa.Column("target_id", sa.Uuid(), nullable=True),
        sa.Column("authorization_result", sa.String(20), nullable=False, server_default="ALLOW"),
        sa.Column("previous_state", sa.JSON(), nullable=True),
        sa.Column("new_state", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_target", "audit_log", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_table("audit_log")
    op.drop_table("app_setting")
    op.drop_table("outbox_job")
    op.drop_table("application_evaluation")
    op.drop_table("application")
    op.drop_table("vacancy")
    op.drop_table("candidate")
    op.drop_table("employee")
    op.drop_table("application_user")
    op.drop_table("designation")
    op.drop_table("department")
    op.drop_table("person")
