"""User management API endpoints."""
from uuid import UUID
from typing import Optional

import secrets
import string

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.user import Organization, User
from app.schemas.user import (
    UserAdminUpdate,
    UserCreate,
    UserListResponse,
    UserResponse,
    UserInviteRequest,
    UserInviteResponse,
    UserTransferRequest,
)
from app.auth.jwt import get_current_active_admin, hash_password
from app.utils.audit import log_audit_event


def _generate_temporary_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))

router = APIRouter(prefix="/users", tags=["Users"])

ALLOWED_USER_ROLES = {"admin", "manager", "user"}
ROLE_ALIASES = {
    "viewer": "user",
    "user": "user",
    "editor": "manager",
    "manager": "manager",
    "admin": "admin",
}


def _normalize_role(role: Optional[str]) -> str:
    if role is None:
        return "user"

    normalized_role = role.strip().lower()
    canonical_role = ROLE_ALIASES.get(normalized_role)

    if canonical_role is None or canonical_role not in ALLOWED_USER_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Invalid role. Allowed values: "
                "admin, manager, user, editor, viewer"
            ),
        )

    return canonical_role


async def _get_user_or_404(user_id: UUID, db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return user


@router.get("", response_model=UserListResponse)
async def list_users(
    organization_id: Optional[UUID] = Query(None, description="Filter by organization"),
    include_inactive: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """List users in the system."""
    query = select(User).order_by(User.created_at.desc())

    if organization_id is not None:
        query = query.where(User.organization_id == organization_id)

    if not include_inactive:
        query = query.where(User.is_active == True)

    result = await db.execute(query)
    users = list(result.scalars().all())

    return UserListResponse(items=users, total=len(users))


@router.post("", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Create a new user."""
    # Validate role
    normalized_role = _normalize_role(data.role) if data.role is not None else None

    # Check email uniqueness
    existing = await db.execute(select(User).where(User.email == data.email))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already exists",
        )

    if data.organization_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == data.organization_id)
        )
        if not org_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization does not exist",
            )

    user = User(
        email=data.email,
        password_hash=hash_password(data.password),
        name=data.name,
        role=normalized_role,
        organization_id=data.organization_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log_audit_event(
        "user_created",
        actor=current_user,
        details={
            "target_user_id": str(user.id),
            "target_email": user.email,
            "target_role": user.role,
            "target_organization_id": str(user.organization_id) if user.organization_id else None,
        },
    )

    return user


@router.post("/invite", response_model=UserInviteResponse, status_code=status.HTTP_201_CREATED)
async def invite_user(
    data: UserInviteRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Invite an existing or new user to an organization with optional role.

    If the user already exists, their organization/role is updated and they are
    re-invited for the target organization.
    If not exists, a temporary password is created and returned in response.
    """
    normalized_role = _normalize_role(data.role) if data.role is not None else None

    if data.organization_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == data.organization_id)
        )
        if not org_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization does not exist",
            )

    existing_user = await db.execute(
        select(User).where(User.email.ilike(data.email))
    )
    user = existing_user.scalar_one_or_none()

    # Existing user: move organization / set role
    if user is not None:
        if normalized_role is not None:
            user.role = normalized_role
        if data.organization_id is not None:
            user.organization_id = data.organization_id
        if data.name is not None and data.name.strip():
            user.name = data.name.strip()

        await db.commit()
        await db.refresh(user)

        log_audit_event(
            "user_invited_existing",
            actor=current_user,
            details={
                "target_user_id": str(user.id),
                "target_user_email": user.email,
                "target_organization_id": str(user.organization_id) if user.organization_id else None,
                "target_role": user.role,
                "inviter_id": str(current_user.id),
            },
        )

        return UserInviteResponse.model_validate(user, update={"created": False, "temporary_password": None})

    # New user path: create with temporary password
    password = _generate_temporary_password()
    user = User(
        email=data.email,
        password_hash=hash_password(password),
        name=data.name.strip() if data.name else None,
        role=normalized_role or "user",
        organization_id=data.organization_id,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    log_audit_event(
        "user_invited_created",
        actor=current_user,
        details={
            "target_user_id": str(user.id),
            "target_user_email": user.email,
            "target_organization_id": str(user.organization_id) if user.organization_id else None,
            "target_role": user.role,
            "inviter_id": str(current_user.id),
            "temporary_password_generated": True,
        },
    )

    return UserInviteResponse.model_validate(
        user,
        update={"created": True, "temporary_password": password},
    )


@router.post("/{user_id}/transfer", response_model=UserResponse)
async def transfer_user(
    user_id: UUID,
    data: UserTransferRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Move a user to another organization and optionally update role."""
    target_user = await _get_user_or_404(user_id, db)
    previous_org_id = target_user.organization_id
    previous_role = target_user.role

    if data.organization_id is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == data.organization_id)
        )
        if not org_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Organization does not exist",
            )
        target_user.organization_id = data.organization_id

    if data.role is not None:
        target_user.role = _normalize_role(data.role)

    await db.commit()
    await db.refresh(target_user)

    log_audit_event(
        "user_transferred",
        actor=current_user,
        details={
            "target_user_id": str(target_user.id),
            "previous_organization_id": str(previous_org_id) if previous_org_id else None,
            "new_organization_id": str(target_user.organization_id) if target_user.organization_id else None,
            "previous_role": previous_role,
            "new_role": target_user.role,
        },
    )

    return target_user


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Get a user by id."""
    return await _get_user_or_404(user_id, db)


@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: UUID,
    data: UserAdminUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Update a user profile and role/organization."""
    user = await _get_user_or_404(user_id, db)
    previous_role = user.role
    previous_org_id = user.organization_id
    updates = data.model_dump(exclude_unset=True)

    if "role" in updates:
        updates["role"] = _normalize_role(updates["role"])

    if "organization_id" in updates and updates["organization_id"] is not None:
        org_result = await db.execute(
            select(Organization).where(Organization.id == updates["organization_id"])
        )
        if not org_result.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Organization does not exist",
            )

    for field, value in updates.items():
        setattr(user, field, value)

    await db.commit()
    await db.refresh(user)

    change_details = {
        "target_user_id": str(user.id),
        "target_email": user.email,
        "updated_fields": sorted(updates.keys()),
    }

    if user.role != previous_role:
        change_details["previous_role"] = previous_role
        change_details["new_role"] = user.role

    if user.organization_id != previous_org_id:
        change_details["previous_organization_id"] = str(previous_org_id) if previous_org_id else None
        change_details["new_organization_id"] = str(user.organization_id) if user.organization_id else None

    log_audit_event(
        "user_updated",
        actor=current_user,
        details=change_details,
    )

    return user


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def deactivate_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Soft-delete user by deactivating account."""
    user = await _get_user_or_404(user_id, db)

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account",
        )

    user.is_active = False
    await db.commit()

    log_audit_event(
        "user_deactivated",
        actor=current_user,
        details={
            "target_user_id": str(user.id),
            "target_email": user.email,
        },
    )


@router.delete("/{user_id}/permanent", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user_permanent(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_admin),
):
    """Permanently delete a user."""
    user = await _get_user_or_404(user_id, db)

    if user.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot delete your own account",
        )

    await db.delete(user)
    await db.commit()

    log_audit_event(
        "user_deleted_permanent",
        actor=current_user,
        details={
            "target_user_id": str(user.id),
            "target_email": user.email,
        },
    )
