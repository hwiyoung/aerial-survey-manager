"""Project Groups API endpoints."""
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.models import ProjectGroup, Project, User
from app.schemas.group import (
    GroupCreate,
    GroupListResponse,
    GroupResponse,
    GroupTreeNode,
    GroupUpdate,
)
from app.auth.jwt import get_current_active_manager, get_current_user, is_admin_role
from app.utils.audit import log_audit_event

router = APIRouter(prefix="/groups", tags=["groups"])


def build_tree(groups: List[ProjectGroup], parent_id: Optional[UUID] = None) -> List[GroupTreeNode]:
    """Build hierarchical tree from flat group list."""
    tree = []
    for group in groups:
        if group.parent_id == parent_id:
            children = build_tree(groups, group.id)
            project_count = len(group.projects) if group.projects else 0
            node = GroupTreeNode(
                id=group.id,
                name=group.name,
                description=group.description,
                color=group.color,
                parent_id=group.parent_id,
                owner_id=group.owner_id,
                organization_id=group.organization_id,
                project_count=project_count,
                created_at=group.created_at,
                updated_at=group.updated_at,
                children=children,
            )
            tree.append(node)
    return tree


def _apply_group_scope(query, current_user: User):
    if is_admin_role(current_user.role):
        return query

    return query.where(
        ProjectGroup.organization_id == current_user.organization_id,
        ProjectGroup.owner_id == current_user.id,
    )


async def _get_scoped_group(group_id: UUID, current_user: User, db: AsyncSession):
    query = select(ProjectGroup).where(ProjectGroup.id == group_id)
    query = _apply_group_scope(query, current_user)
    result = await db.execute(query)
    return result.scalar_one_or_none()


@router.get("", response_model=GroupListResponse)
async def list_groups(
    flat: bool = Query(False, description="Return flat list instead of tree"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get all groups for current user (hierarchical by default)."""
    query = (
        select(ProjectGroup)
        .options(selectinload(ProjectGroup.projects))
        .order_by(ProjectGroup.name)
    )
    query = _apply_group_scope(query, current_user)
    result = await db.execute(query)
    groups = list(result.scalars().all())

    if flat:
        items = [
            GroupResponse(
                id=g.id,
                name=g.name,
                description=g.description,
                color=g.color,
                parent_id=g.parent_id,
                owner_id=g.owner_id,
                organization_id=g.organization_id,
                project_count=len(g.projects) if g.projects else 0,
                created_at=g.created_at,
                updated_at=g.updated_at,
            )
            for g in groups
        ]
        return GroupListResponse(items=items, total=len(items))

    # Build tree structure
    tree = build_tree(groups)
    return GroupListResponse(items=tree, total=len(groups))


@router.post("", response_model=GroupResponse, status_code=status.HTTP_201_CREATED)
async def create_group(
    group_data: GroupCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_manager),
):
    """Create a new project group."""
    if group_data.parent_id:
        parent_query = select(ProjectGroup).where(
            ProjectGroup.id == group_data.parent_id,
            ProjectGroup.owner_id == current_user.id,
            ProjectGroup.organization_id == current_user.organization_id,
        )
        parent_result = await db.execute(parent_query)
        if not parent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent group not found",
            )

    group = ProjectGroup(
        name=group_data.name,
        description=group_data.description,
        color=group_data.color,
        parent_id=group_data.parent_id,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    db.add(group)
    await db.commit()
    await db.refresh(group)

    log_audit_event(
        "group_created",
        actor=current_user,
        details={
            "group_id": str(group.id),
            "group_name": group.name,
            "organization_id": str(group.organization_id) if group.organization_id else None,
            "owner_id": str(group.owner_id),
            "parent_id": str(group.parent_id) if group.parent_id else None,
        },
    )

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        color=group.color,
        parent_id=group.parent_id,
        owner_id=group.owner_id,
        organization_id=group.organization_id,
        project_count=0,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.get("/{group_id}", response_model=GroupResponse)
async def get_group(
    group_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a specific group."""
    query = _apply_group_scope(
        select(ProjectGroup)
        .options(selectinload(ProjectGroup.projects))
        .where(ProjectGroup.id == group_id),
        current_user,
    )
    result = await db.execute(query)
    group = result.scalar_one_or_none()

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        color=group.color,
        parent_id=group.parent_id,
        owner_id=group.owner_id,
        organization_id=group.organization_id,
        project_count=len(group.projects) if group.projects else 0,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.patch("/{group_id}", response_model=GroupResponse)
async def update_group(
    group_id: UUID,
    group_data: GroupUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_manager),
):
    """Update a group."""
    group = await _get_scoped_group(group_id, current_user, db)

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    # Prevent circular reference
    if group_data.parent_id and group_data.parent_id == group_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Group cannot be its own parent",
        )

    if group_data.parent_id:
        parent_query = select(ProjectGroup).where(
            ProjectGroup.id == group_data.parent_id,
            ProjectGroup.owner_id == current_user.id,
            ProjectGroup.organization_id == current_user.organization_id,
        )
        parent_result = await db.execute(parent_query)
        if not parent_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Parent group not found",
            )

    update_data = group_data.model_dump(exclude_unset=True)
    previous_name = group.name
    previous_parent_id = group.parent_id

    for field, value in update_data.items():
        setattr(group, field, value)

    await db.commit()
    await db.refresh(group)

    log_audit_event(
        "group_updated",
        actor=current_user,
        details={
            "group_id": str(group.id),
            "previous_name": previous_name,
            "new_name": group.name,
            "previous_parent_id": str(previous_parent_id) if previous_parent_id else None,
            "new_parent_id": str(group.parent_id) if group.parent_id else None,
            "updated_fields": sorted(update_data.keys()),
        },
    )

    return GroupResponse(
        id=group.id,
        name=group.name,
        description=group.description,
        color=group.color,
        parent_id=group.parent_id,
        owner_id=group.owner_id,
        organization_id=group.organization_id,
        project_count=len(group.projects) if group.projects else 0,
        created_at=group.created_at,
        updated_at=group.updated_at,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(
    group_id: UUID,
    mode: str = Query("keep", description="keep: keep projects, delete: delete projects"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_manager),
):
    """Delete a group. Mode determines what happens to projects."""
    group = await _get_scoped_group(group_id, current_user, db)

    if not group:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Group not found",
        )

    if mode == "keep":
        await db.execute(
            Project.__table__.update()
            .where(
                Project.group_id == group_id,
                Project.organization_id == current_user.organization_id,
            )
            .values(group_id=None)
        )
    elif mode == "delete":
        await db.execute(
            Project.__table__.delete()
            .where(
                Project.group_id == group_id,
                Project.organization_id == current_user.organization_id,
            )
        )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid mode. Use 'keep' or 'delete'",
        )

    await db.delete(group)
    await db.commit()

    log_audit_event(
        "group_deleted",
        actor=current_user,
        details={
            "group_id": str(group.id),
            "group_name": group.name,
            "mode": mode,
            "organization_id": str(group.organization_id) if group.organization_id else None,
            "owner_id": str(group.owner_id),
        },
    )
