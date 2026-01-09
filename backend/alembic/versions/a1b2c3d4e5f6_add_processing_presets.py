"""add processing presets table

Revision ID: a1b2c3d4e5f6
Revises: f8abbb33b9d6
Create Date: 2026-01-09 18:45:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = 'a1b2c3d4e5f6'
down_revision = 'f8abbb33b9d6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'processing_presets',
        sa.Column('id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('options', postgresql.JSON(astext_type=sa.Text()), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_processing_presets_user_id', 'processing_presets', ['user_id'])


def downgrade() -> None:
    op.drop_index('ix_processing_presets_user_id', table_name='processing_presets')
    op.drop_table('processing_presets')
