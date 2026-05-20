"""add image validation status

Revision ID: f2a7c8d9e0b1
Revises: 6e5a787f17c3
Create Date: 2026-05-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f2a7c8d9e0b1'
down_revision: Union[str, None] = '6e5a787f17c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('images', sa.Column('validation_status', sa.String(length=20), nullable=True))
    op.add_column('images', sa.Column('validation_error', sa.Text(), nullable=True))
    op.add_column('images', sa.Column('validated_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('images', 'validated_at')
    op.drop_column('images', 'validation_error')
    op.drop_column('images', 'validation_status')
