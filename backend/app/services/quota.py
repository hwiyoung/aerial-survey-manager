"""Organization quota enforcement helpers."""

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import Project, Image
from app.models.user import Organization

_BYTES_PER_GB = 1024 * 1024 * 1024


async def _get_organization_or_404(
    db: AsyncSession,
    organization_id,
) -> Organization:
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


async def ensure_organization_quota(
    db: AsyncSession,
    organization_id,
    *,
    additional_projects: int = 0,
    additional_storage_bytes: int = 0,
):
    """Validate quota for a user action that creates resources."""
    if organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization context is required",
        )

    if additional_projects <= 0 and additional_storage_bytes <= 0:
        return

    organization = await _get_organization_or_404(db, organization_id)

    if additional_projects > 0:
        project_count_result = await db.execute(
            select(func.count(Project.id)).where(Project.organization_id == organization_id)
        )
        project_count = project_count_result.scalar_one()
        if project_count + additional_projects > organization.quota_projects:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "ORG_PROJECT_QUOTA_EXCEEDED",
                    "message": "조직 프로젝트 할당량을 초과했습니다.",
                    "current": project_count,
                    "limit": organization.quota_projects,
                    "requested": additional_projects,
                },
            )

    if additional_storage_bytes > 0:
        storage_result = await db.execute(
            select(func.coalesce(func.sum(Image.file_size), 0))
            .select_from(Project)
            .join(Image, Project.id == Image.project_id, isouter=True)
            .where(Project.organization_id == organization_id)
        )
        used_bytes = int(storage_result.scalar_one() or 0)
        quota_bytes = int(organization.quota_storage_gb * _BYTES_PER_GB)

        if used_bytes + additional_storage_bytes > quota_bytes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error_code": "ORG_STORAGE_QUOTA_EXCEEDED",
                    "message": "조직 스토리지 할당량을 초과했습니다.",
                    "current_bytes": used_bytes,
                    "limit_bytes": quota_bytes,
                    "requested_bytes": additional_storage_bytes,
                },
            )
