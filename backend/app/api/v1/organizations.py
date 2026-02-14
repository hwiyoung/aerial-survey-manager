"""Organization management API endpoints."""
from uuid import UUID
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.group import ProjectGroup
from app.models.project import CameraModel, Project
from app.models.user import Organization, User
from app.schemas.user import (
    OrganizationCreate,
    OrganizationListResponse,
    OrganizationResponse,
    OrganizationUpdate,
    UserListResponse,
)
from app.auth.jwt import get_current_active_admin
from app.utils.audit import log_audit_event

router = APIRouter(prefix="/organizations", tags=["Organizations"])


async def _get_organization_or_404(organization_id: UUID, db: AsyncSession) -> Organization:
    result = await db.execute(
        select(Organization).where(Organization.id == organization_id)
    )
    organization = result.scalar_one_or_none()
    if not organization:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Organization not found",
        )

    return organization


def _validate_quota(value: Optional[int], field_name: str) -> None:
    if value is not None and value < 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"{field_name} must be 0 or greater",
        )


@router.get("", response_model=OrganizationListResponse)
async def list_organizations(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """List all organizations."""
    query = select(Organization).order_by(Organization.created_at.desc())
    result = await db.execute(query)
    organizations = list(result.scalars().all())

    return OrganizationListResponse(items=organizations, total=len(organizations))


@router.post("", response_model=OrganizationResponse, status_code=status.HTTP_201_CREATED)
async def create_organization(
    data: OrganizationCreate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """Create a new organization."""
    _validate_quota(data.quota_storage_gb, "Storage quota (GB)")
    _validate_quota(data.quota_projects, "Project quota")

    organization = Organization(
        name=data.name,
        quota_storage_gb=data.quota_storage_gb,
        quota_projects=data.quota_projects,
    )
    db.add(organization)
    await db.commit()
    await db.refresh(organization)

    log_audit_event(
        "organization_created",
        actor=current_user,
        details={
            "organization_id": str(organization.id),
            "organization_name": organization.name,
            "quota_storage_gb": organization.quota_storage_gb,
            "quota_projects": organization.quota_projects,
        },
    )

    return organization


@router.get("/{organization_id}", response_model=OrganizationResponse)
async def get_organization(
    organization_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """Get organization details."""
    return await _get_organization_or_404(organization_id, db)


@router.patch("/{organization_id}", response_model=OrganizationResponse)
async def update_organization(
    organization_id: UUID,
    data: OrganizationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """Update organization quota and metadata."""
    organization = await _get_organization_or_404(organization_id, db)
    previous_name = organization.name
    previous_quota_storage_gb = organization.quota_storage_gb
    previous_quota_projects = organization.quota_projects
    updates = data.model_dump(exclude_unset=True)

    if not updates:
        return organization

    _validate_quota(updates.get("quota_storage_gb"), "Storage quota (GB)")
    _validate_quota(updates.get("quota_projects"), "Project quota")

    for field, value in updates.items():
        setattr(organization, field, value)

    await db.commit()
    await db.refresh(organization)

    log_audit_event(
        "organization_updated",
        actor=current_user,
        details={
            "organization_id": str(organization.id),
            "previous_name": previous_name,
            "new_name": organization.name,
            "previous_quota_storage_gb": previous_quota_storage_gb,
            "new_quota_storage_gb": organization.quota_storage_gb,
            "previous_quota_projects": previous_quota_projects,
            "new_quota_projects": organization.quota_projects,
            "updated_fields": sorted(updates.keys()),
        },
    )

    return organization


@router.delete("/{organization_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_organization(
    organization_id: UUID,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """Delete an organization.

    기본 동작은 참조 데이터(사용자/프로젝트/그룹/카메라 모델)가 없을 때만 삭제됩니다.
    force=true인 경우 참조를 먼저 해제한 뒤 조직을 삭제합니다.
    """
    organization = await _get_organization_or_404(organization_id, db)

    user_count = (
        await db.execute(
            select(func.count(User.id)).where(User.organization_id == organization_id)
        )
    ).scalar_one()

    project_count = (
        await db.execute(
            select(func.count(Project.id)).where(Project.organization_id == organization_id)
        )
    ).scalar_one()

    group_count = (
        await db.execute(
            select(func.count(ProjectGroup.id)).where(ProjectGroup.organization_id == organization_id)
        )
    ).scalar_one()

    camera_model_count = (
        await db.execute(
            select(func.count(CameraModel.id)).where(CameraModel.organization_id == organization_id)
        )
    ).scalar_one()

    has_dependencies = (
        user_count > 0
        or project_count > 0
        or group_count > 0
        or camera_model_count > 0
    )
    dependency_snapshot = {
        "user_count": user_count,
        "project_count": project_count,
        "group_count": group_count,
        "camera_model_count": camera_model_count,
    }

    if has_dependencies and not force:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization has dependencies. Remove users, projects, groups, and camera models before deletion.",
        )
    if has_dependencies and force:
        # Force mode: detach all organization-scoped resources first.
        await db.execute(update(User).where(User.organization_id == organization_id).values(organization_id=None))
        await db.execute(update(Project).where(Project.organization_id == organization_id).values(organization_id=None))
        await db.execute(update(ProjectGroup).where(ProjectGroup.organization_id == organization_id).values(organization_id=None))
        await db.execute(
            update(CameraModel)
            .where(CameraModel.organization_id == organization_id)
            .values(organization_id=None)
        )

    organization_name = organization.name
    await db.delete(organization)
    await db.commit()

    log_audit_event(
        "organization_deleted",
        actor=current_user,
        details={
            "organization_id": str(organization_id),
            "organization_name": organization_name,
            "force": force,
            "dependency_counts_before_delete": dependency_snapshot,
            "forced_detach": force and has_dependencies,
        },
    )


@router.get("/{organization_id}/users", response_model=UserListResponse)
async def list_organization_users(
    organization_id: UUID,
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_active_admin),
):
    """List members in an organization."""
    await _get_organization_or_404(organization_id, db)

    query = (
        select(User)
        .where(User.organization_id == organization_id)
        .order_by(User.created_at.desc())
    )

    if not include_inactive:
        query = query.where(User.is_active == True)

    result = await db.execute(query)
    users = list(result.scalars().all())

    return UserListResponse(items=users, total=len(users))
