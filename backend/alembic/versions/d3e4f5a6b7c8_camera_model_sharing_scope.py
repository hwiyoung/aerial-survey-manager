"""enforce organization-scoped camera model sharing

Revision ID: d3e4f5a6b7c8
Revises: c2d3e4f5a6b7
Create Date: 2026-07-16 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3e4f5a6b7c8"
down_revision: Union[str, None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    connection = op.get_bind()

    empty_name = connection.execute(
        sa.text(
            """
            SELECT id
            FROM camera_models
            WHERE btrim(name) = ''
            LIMIT 1
            """
        )
    ).mappings().first()
    if empty_name:
        raise RuntimeError(
            "Cannot enforce camera model names: "
            f"camera model {empty_name['id']} has an empty name."
        )

    invalid_scope = connection.execute(
        sa.text(
            """
            SELECT id, is_custom, organization_id
            FROM camera_models
            WHERE NOT (
                (is_custom = false AND organization_id IS NULL)
                OR (is_custom = true AND organization_id IS NOT NULL)
            )
            LIMIT 1
            """
        )
    ).mappings().first()
    if invalid_scope:
        raise RuntimeError(
            "Cannot enforce camera model sharing scope: "
            f"camera model {invalid_scope['id']} has "
            f"is_custom={invalid_scope['is_custom']} and "
            f"organization_id={invalid_scope['organization_id']}."
        )

    duplicate = connection.execute(
        sa.text(
            """
            SELECT organization_id, lower(btrim(name)) AS normalized_name,
                   COUNT(*) AS duplicate_count
            FROM camera_models
            GROUP BY organization_id, lower(btrim(name))
            HAVING COUNT(*) > 1
            LIMIT 1
            """
        )
    ).mappings().first()
    if duplicate:
        scope = duplicate["organization_id"] or "public"
        raise RuntimeError(
            "Cannot enforce camera model name uniqueness: "
            f"scope={scope} name={duplicate['normalized_name']!r} has "
            f"{duplicate['duplicate_count']} records."
        )

    connection.execute(
        sa.text("UPDATE camera_models SET name = btrim(name) WHERE name <> btrim(name)")
    )

    op.create_check_constraint(
        "ck_camera_models_sharing_scope",
        "camera_models",
        "(is_custom = false AND organization_id IS NULL) OR "
        "(is_custom = true AND organization_id IS NOT NULL)",
    )
    op.create_index(
        "uq_camera_models_public_name_ci",
        "camera_models",
        [sa.text("lower(TRIM(BOTH FROM name))")],
        unique=True,
        postgresql_where=sa.text("organization_id IS NULL"),
    )
    op.create_index(
        "uq_camera_models_org_name_ci",
        "camera_models",
        ["organization_id", sa.text("lower(TRIM(BOTH FROM name))")],
        unique=True,
        postgresql_where=sa.text("organization_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_camera_models_org_name_ci",
        table_name="camera_models",
    )
    op.drop_index(
        "uq_camera_models_public_name_ci",
        table_name="camera_models",
    )
    op.drop_constraint(
        "ck_camera_models_sharing_scope",
        "camera_models",
        type_="check",
    )
