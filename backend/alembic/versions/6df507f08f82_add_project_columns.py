"""add project columns

Revision ID: 6df507f08f82
Revises: 5cf406f07f71
Create Date: 2026-02-02 23:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '6df507f08f82'
down_revision: Union[str, None] = '5cf406f07f71'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add missing columns to projects table
    op.add_column('projects', sa.Column('area', sa.Float(), nullable=True))
    op.add_column('projects', sa.Column('source_size', sa.BigInteger(), nullable=True))
    op.add_column('projects', sa.Column('ortho_size', sa.BigInteger(), nullable=True))
    op.add_column('projects', sa.Column('ortho_path', sa.String(length=500), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'ortho_path')
    op.drop_column('projects', 'ortho_size')
    op.drop_column('projects', 'source_size')
    op.drop_column('projects', 'area')
