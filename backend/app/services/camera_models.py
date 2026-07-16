"""Camera model visibility and ownership helpers."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import is_admin_role
from app.models.project import CameraModel
from app.models.user import User


def normalize_camera_model_name(name: str) -> str:
    """Return the canonical stored form for a camera model name."""
    normalized = name.strip()
    if not normalized:
        raise ValueError("Camera model name must not be empty.")
    return normalized


def apply_camera_model_access_scope(query, user: User):
    """Limit camera models to public standards and the user's organization."""
    if is_admin_role(user.role):
        return query

    public_standard = and_(
        CameraModel.organization_id.is_(None),
        CameraModel.is_custom.is_(False),
    )
    if user.organization_id is None:
        return query.where(public_standard)

    organization_custom = and_(
        CameraModel.organization_id == user.organization_id,
        CameraModel.is_custom.is_(True),
    )
    return query.where(or_(public_standard, organization_custom))


async def resolve_accessible_camera_model(
    db: AsyncSession,
    camera_model_id: UUID,
    user: User,
) -> CameraModel | None:
    """Resolve a model by UUID without crossing its visibility boundary."""
    query = select(CameraModel).where(CameraModel.id == camera_model_id)
    query = apply_camera_model_access_scope(query, user)
    result = await db.execute(query)
    return result.scalar_one_or_none()


def can_manage_camera_model(camera_model: CameraModel, user: User) -> bool:
    """Return whether a user may update or delete the model."""
    if is_admin_role(user.role):
        return True
    return bool(
        user.organization_id is not None
        and camera_model.is_custom
        and camera_model.organization_id == user.organization_id
    )


def custom_model_organization_id(user: User) -> UUID:
    """Return the organization that owns a new custom model."""
    if user.organization_id is None:
        raise ValueError(
            "Organization membership is required to create a shared camera model."
        )
    return user.organization_id


async def camera_model_name_exists(
    db: AsyncSession,
    *,
    name: str,
    organization_id: UUID | None,
    exclude_id: UUID | None = None,
) -> bool:
    """Check case-insensitive uniqueness inside one sharing scope."""
    normalized_name = normalize_camera_model_name(name)
    query = select(CameraModel.id).where(
        func.lower(func.trim(CameraModel.name)) == normalized_name.lower()
    )
    if organization_id is None:
        query = query.where(CameraModel.organization_id.is_(None))
    else:
        query = query.where(CameraModel.organization_id == organization_id)
    if exclude_id is not None:
        query = query.where(CameraModel.id != exclude_id)

    result = await db.execute(query.limit(1))
    return result.scalar_one_or_none() is not None
