"""Add sensor pixel dimensions to CameraModel

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, None] = 'c3d4e5f6a7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add sensor pixel dimensions to camera_models
    op.add_column('camera_models', sa.Column('sensor_width_px', sa.Integer(), nullable=True))
    op.add_column('camera_models', sa.Column('sensor_height_px', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('camera_models', 'sensor_height_px')
    op.drop_column('camera_models', 'sensor_width_px')
