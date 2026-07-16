"""persist processing options on jobs

Revision ID: c2d3e4f5a6b7
Revises: b1c2d3e4f5a7
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "c2d3e4f5a6b7"
down_revision: Union[str, None] = "b1c2d3e4f5a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column(
            "processing_options",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.execute(
        """
        UPDATE processing_jobs
        SET processing_options = jsonb_build_object(
            'engine', engine,
            'gsd', gsd,
            'output_crs', output_crs,
            'output_format', output_format,
            'process_mode', COALESCE(process_mode, 'Normal'),
            'eo_only_align', true,
            'build_point_cloud', false,
            'resume_checkpoint', true
        )
        """
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "processing_options")
