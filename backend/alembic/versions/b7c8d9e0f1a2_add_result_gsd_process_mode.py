"""Add result_gsd and process_mode to ProcessingJob

Revision ID: b7c8d9e0f1a2
Revises: 5cf406f07f71
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c8d9e0f1a2'
down_revision: Union[str, None] = '5cf406f07f71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add result_gsd column (처리 결과 GSD, cm/pixel)
    op.add_column('processing_jobs', sa.Column('result_gsd', sa.Float(), nullable=True))
    # Add process_mode column (Preview, Normal, High)
    op.add_column('processing_jobs', sa.Column('process_mode', sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column('processing_jobs', 'process_mode')
    op.drop_column('processing_jobs', 'result_gsd')
