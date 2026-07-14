"""add crs correction fields

Revision ID: a9c1d2e3f4b5
Revises: f2a7c8d9e0b1
Create Date: 2026-06-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a9c1d2e3f4b5"
down_revision: Union[str, None] = "f2a7c8d9e0b1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("processing_jobs", sa.Column("crs_correction_source_crs", sa.String(length=50), nullable=True))
    op.add_column("processing_jobs", sa.Column("crs_correction_status", sa.String(length=20), nullable=True))
    op.add_column("processing_jobs", sa.Column("crs_correction_requested_at", sa.DateTime(), nullable=True))
    op.add_column("processing_jobs", sa.Column("crs_correction_applied_at", sa.DateTime(), nullable=True))
    op.add_column("processing_jobs", sa.Column("crs_correction_error", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("processing_jobs", "crs_correction_error")
    op.drop_column("processing_jobs", "crs_correction_applied_at")
    op.drop_column("processing_jobs", "crs_correction_requested_at")
    op.drop_column("processing_jobs", "crs_correction_status")
    op.drop_column("processing_jobs", "crs_correction_source_crs")
