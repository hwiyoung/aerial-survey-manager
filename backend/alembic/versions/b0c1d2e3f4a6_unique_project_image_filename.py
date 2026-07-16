"""prevent duplicate image filenames within a project

Revision ID: b0c1d2e3f4a6
Revises: a9c1d2e3f4b5
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b0c1d2e3f4a6"
down_revision: Union[str, None] = "a9c1d2e3f4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()
    duplicate = connection.execute(
        sa.text(
            """
            SELECT project_id, filename, COUNT(*) AS duplicate_count
            FROM images
            GROUP BY project_id, filename
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate:
        raise RuntimeError(
            "Cannot add image filename constraint: duplicate rows exist for "
            f"project={duplicate['project_id']} filename={duplicate['filename']!r}. "
            "Resolve the duplicate records before retrying the migration."
        )

    op.create_unique_constraint(
        "uq_images_project_filename",
        "images",
        ["project_id", "filename"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_images_project_filename",
        "images",
        type_="unique",
    )
