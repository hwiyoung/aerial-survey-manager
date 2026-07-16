"""add processing job timestamps and one-active-job guard

Revision ID: b1c2d3e4f5a7
Revises: b0c1d2e3f4a6
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b1c2d3e4f5a7"
down_revision: Union[str, None] = "b0c1d2e3f4a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


ACTIVE_STATUS_SQL = "'scheduled', 'queued', 'processing'"


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("queued_at", sa.DateTime(), nullable=True),
    )

    connection = op.get_bind()
    connection.execute(
        sa.text(
            """
            UPDATE processing_jobs
            SET queued_at = COALESCE(started_at, created_at)
            WHERE status IN ('queued', 'processing')
              AND queued_at IS NULL
            """
        )
    )

    duplicate = connection.execute(
        sa.text(
            f"""
            SELECT project_id, COUNT(*) AS active_count
            FROM processing_jobs
            WHERE status IN ({ACTIVE_STATUS_SQL})
            GROUP BY project_id
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate:
        raise RuntimeError(
            "Cannot enforce one active processing job per project: "
            f"project={duplicate['project_id']} has {duplicate['active_count']} active jobs. "
            "Resolve the duplicate jobs before retrying the migration."
        )

    op.create_index(
        "uq_processing_jobs_one_active_per_project",
        "processing_jobs",
        ["project_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('scheduled', 'queued', 'processing')"
        ),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_processing_jobs_one_active_per_project",
        table_name="processing_jobs",
    )
    op.drop_column("processing_jobs", "queued_at")
    op.drop_column("processing_jobs", "created_at")
