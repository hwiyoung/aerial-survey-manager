"""Project API endpoints."""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
)
from app.auth.jwt import get_current_user, PermissionChecker

router = APIRouter(prefix="/projects", tags=["Projects"])


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    region: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects accessible by the current user."""
    # Build query based on user's access
    query = select(Project)
    
    # Filter by ownership or organization
    if current_user.role != "admin":
        query = query.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
    
    # Apply filters
    if status_filter:
        query = query.where(Project.status == status_filter)
    if region:
        query = query.where(Project.region == region)
    if search:
        query = query.where(Project.title.ilike(f"%{search}%"))
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Paginate
    query = query.order_by(Project.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    projects = result.scalars().all()
    
    # Add image count to each project
    project_responses = []
    for project in projects:
        count_result = await db.execute(
            select(func.count()).where(Image.project_id == project.id)
        )
        image_count = count_result.scalar()
        
        response = ProjectResponse.model_validate(project)
        response.image_count = image_count
        project_responses.append(response)
    
    return ProjectListResponse(
        items=project_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    project = Project(
        title=data.title,
        region=data.region,
        company=data.company,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)
    
    response = ProjectResponse.model_validate(project)
    response.image_count = 0
    return response


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project details."""
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Get image count
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()
    
    response = ProjectResponse.model_validate(project)
    response.image_count = image_count
    return response


@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project."""
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(project, field, value)
    
    await db.flush()
    await db.refresh(project)
    
    # Get image count
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()
    
    response = ProjectResponse.model_validate(project)
    response.image_count = image_count
    return response


@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete project and all related data."""
    # Check permission (only owner or admin can delete)
    permission_checker = PermissionChecker("admin")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner or admin can delete projects",
        )
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    await db.delete(project)
    # Note: Related images, jobs, etc. will be deleted via CASCADE
