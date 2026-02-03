"""Add PPA to CameraModel and image dimensions to Image

Revision ID: c3d4e5f6a7b8
Revises: b7c8d9e0f1a2
Create Date: 2025-02-03

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b7c8d9e0f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add PPA columns to camera_models
    op.add_column('camera_models', sa.Column('ppa_x', sa.Float(), nullable=True))
    op.add_column('camera_models', sa.Column('ppa_y', sa.Float(), nullable=True))

    # Add image dimensions to images
    op.add_column('images', sa.Column('image_width', sa.Integer(), nullable=True))
    op.add_column('images', sa.Column('image_height', sa.Integer(), nullable=True))
    op.add_column('images', sa.Column('camera_model_id', sa.UUID(), nullable=True))

    # Add foreign key constraint
    op.create_foreign_key(
        'fk_images_camera_model_id',
        'images', 'camera_models',
        ['camera_model_id'], ['id']
    )


def downgrade() -> None:
    # Remove foreign key first
    op.drop_constraint('fk_images_camera_model_id', 'images', type_='foreignkey')

    # Remove columns from images
    op.drop_column('images', 'camera_model_id')
    op.drop_column('images', 'image_height')
    op.drop_column('images', 'image_width')

    # Remove PPA columns from camera_models
    op.drop_column('camera_models', 'ppa_y')
    op.drop_column('camera_models', 'ppa_x')
