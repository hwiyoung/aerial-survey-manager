"""Permission metadata and project permission assignment API."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.project import Project
from app.models.user import ProjectPermission, User
from app.schemas.user import (
    PermissionCatalogResponse,
    PermissionDescriptor,
    ProjectPermissionListResponse,
    ProjectPermissionRequest,
    ProjectPermissionResponse,
)
from app.auth.jwt import get_current_active_admin
from app.utils.audit import log_audit_event

router = APIRouter(prefix="/permissions", tags=["Permissions"])

ALLOWED_PROJECT_PERMISSIONS = {"view", "edit", "admin"}
ROLE_OPTIONS = [
    PermissionDescriptor(
        value="admin",
        label="관리자",
        description="전체 권한 관리와 사용자/조직 설정 가능",
    ),
    PermissionDescriptor(
        value="manager",
        label="편집자",
        description="프로젝트 생성/수정/처리 실행 권한",
    ),
    PermissionDescriptor(
        value="user",
        label="뷰어",
        description="프로젝트 조회 및 다운로드 권한",
    ),
]
PROJECT_PERMISSION_OPTIONS = [
    PermissionDescriptor(
        value="view",
        label="View",
        description="프로젝트 조회 권한",
    ),
    PermissionDescriptor(
        value="edit",
        label="Edit",
        description="프로젝트 편집 및 업로드 권한",
    ),
    PermissionDescriptor(
        value="admin",
        label="Admin",
        description="프로젝트 멤버 및 권한 관리 권한",
    ),
]


@router.get("/roles", response_model=PermissionCatalogResponse)
async def get_permission_catalog(
    current_user: User = Depends(get_current_active_admin),
):
    """Return supported platform roles and project permission levels."""
    return PermissionCatalogResponse(
        roles=ROLE_OPTIONS,
        project_permissions=PROJECT_PERMISSION_OPTIONS,
    )


@router.get("/projects/{project_id}", response_model=ProjectPermissionListResponse)
async def list_project_permissions(
    project_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """List explicit project permissions."""
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    result = await db.execute(
        select(ProjectPermission, User.email)
        .join(User, User.id == ProjectPermission.user_id)
        .where(ProjectPermission.project_id == project_id)
        .order_by(ProjectPermission.granted_at.desc())
    )
    rows = result.all()

    permissions = [
        ProjectPermissionResponse(
            id=permission.id,
            project_id=permission.project_id,
            user_id=permission.user_id,
            permission=permission.permission,
            user_email=email,
            granted_at=permission.granted_at,
        )
        for permission, email in rows
    ]

    return ProjectPermissionListResponse(
        project_id=project_id,
        items=permissions,
        total=len(permissions),
    )


@router.put(
    "/projects/{project_id}/users/{user_id}",
    response_model=ProjectPermissionResponse,
)
async def set_project_permission(
    project_id: UUID,
    user_id: UUID,
    data: ProjectPermissionRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Create or update a project permission for a user."""
    permission = data.permission.strip().lower()
    if permission not in ALLOWED_PROJECT_PERMISSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid permission. Allowed values are "
                f"{sorted(ALLOWED_PROJECT_PERMISSIONS)}"
            ),
        )

    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    if project.organization_id != user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Project and user must belong to the same organization",
        )

    result = await db.execute(
        select(ProjectPermission).where(
            ProjectPermission.project_id == project_id,
            ProjectPermission.user_id == user_id,
        )
    )
    permission_row = result.scalar_one_or_none()

    if permission_row:
        permission_row.permission = permission
    else:
        permission_row = ProjectPermission(
            project_id=project_id,
            user_id=user_id,
            permission=permission,
        )
        db.add(permission_row)

    await db.commit()
    await db.refresh(permission_row)

    log_audit_event(
        "project_permission_upserted",
        actor=current_user,
        details={
            "project_id": str(project_id),
            "project_organization_id": str(project.organization_id) if project.organization_id else None,
            "target_user_id": str(user.id),
            "target_user_email": user.email,
            "permission": permission_row.permission,
        },
    )

    return ProjectPermissionResponse(
        id=permission_row.id,
        project_id=permission_row.project_id,
        user_id=permission_row.user_id,
        permission=permission_row.permission,
        user_email=user.email,
        granted_at=permission_row.granted_at,
    )


@router.delete(
    "/projects/{project_id}/users/{user_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def remove_project_permission(
    project_id: UUID,
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Remove explicit permission for a user on a project."""
    target_user = await db.get(User, user_id)

    result = await db.execute(
        select(ProjectPermission).where(
            ProjectPermission.project_id == project_id,
            ProjectPermission.user_id == user_id,
        )
    )
    permission_row = result.scalar_one_or_none()

    if not permission_row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project permission not found",
        )

    await db.delete(permission_row)
    await db.commit()

    log_audit_event(
        "project_permission_removed",
        actor=current_user,
        details={
            "project_id": str(project_id),
            "target_user_id": str(user_id),
            "target_user_email": target_user.email if target_user else None,
            "previous_permission": permission_row.permission,
        },
    )
