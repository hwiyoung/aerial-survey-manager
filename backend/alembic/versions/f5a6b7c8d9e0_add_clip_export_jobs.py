"""add durable asynchronous clip export jobs

Revision ID: f5a6b7c8d9e0
Revises: e4f5a6b7c8d9
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f5a6b7c8d9e0"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "clip_export_jobs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=True),
        sa.Column("project_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("sheet_ids", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scale", sa.Integer(), nullable=False),
        sa.Column("output_format", sa.String(length=20), nullable=False),
        sa.Column("output_crs", sa.String(length=20), nullable=False),
        sa.Column("output_gsd", sa.Float(), nullable=True),
        sa.Column("base_filename", sa.String(length=160), nullable=False),
        sa.Column("output_filename", sa.String(length=180), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("stage", sa.String(length=80), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_reference", sa.String(length=40), nullable=True),
        sa.Column("result_path", sa.String(length=500), nullable=True),
        sa.Column("result_size", sa.BigInteger(), nullable=True),
        sa.Column("celery_task_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_clip_export_jobs_user_created",
        "clip_export_jobs",
        ["user_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_clip_export_jobs_status",
        "clip_export_jobs",
        ["status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_clip_export_jobs_status", table_name="clip_export_jobs")
    op.drop_index("ix_clip_export_jobs_user_created", table_name="clip_export_jobs")
    op.drop_table("clip_export_jobs")
