"""Add stable processing error code and reference.

Revision ID: e4f5a6b7c8d9
Revises: d3e4f5a6b7c8
Create Date: 2026-07-22
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e4f5a6b7c8d9"
down_revision: Union[str, None] = "d3e4f5a6b7c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "processing_jobs",
        sa.Column("error_code", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "processing_jobs",
        sa.Column("error_reference", sa.String(length=40), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("processing_jobs", "error_reference")
    op.drop_column("processing_jobs", "error_code")
