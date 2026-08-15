"""Create the durable generation job table.

Revision ID: 20260815_0001
Revises: None
"""

import sqlalchemy as sa
from alembic import op

revision = "20260815_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "generation_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("client_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key_hash", sa.String(length=64), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("model_name", sa.String(length=200), nullable=False),
        sa.Column("instructions", sa.Text(), nullable=False),
        sa.Column("max_output_tokens", sa.Integer(), nullable=False),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("provider_response_id", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("total_tokens", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("error_message", sa.String(length=500), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed')",
            name="generation_jobs_status_valid",
        ),
        sa.CheckConstraint(
            "max_output_tokens > 0 AND max_output_tokens <= 4096",
            name="generation_jobs_output_tokens_valid",
        ),
        sa.CheckConstraint(
            "attempts >= 0 AND max_attempts > 0 "
            "AND max_attempts <= 10 AND attempts <= max_attempts",
            name="generation_jobs_attempts_valid",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "client_id",
            "idempotency_key_hash",
            name="generation_jobs_client_idempotency_uq",
        ),
    )
    op.create_index(
        "generation_jobs_claim_idx",
        "generation_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_generation_jobs_client_id",
        "generation_jobs",
        ["client_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_generation_jobs_client_id", table_name="generation_jobs")
    op.drop_index("generation_jobs_claim_idx", table_name="generation_jobs")
    op.drop_table("generation_jobs")
