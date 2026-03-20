"""add ortho_thumbnail_path to projects

Revision ID: 97e6f82943ae
Revises: e1f2a3b4c5d6
Create Date: 2026-03-18 09:09:56.328660

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import geoalchemy2


# revision identifiers, used by Alembic.
revision: str = '97e6f82943ae'
down_revision: Union[str, None] = 'e1f2a3b4c5d6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('projects', sa.Column('ortho_thumbnail_path', sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column('projects', 'ortho_thumbnail_path')
