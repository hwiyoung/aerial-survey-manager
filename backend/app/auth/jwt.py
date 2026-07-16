"""JWT Authentication utilities."""
from datetime import datetime, timedelta
from typing import Optional
import bcrypt
import jwt
from jwt import PyJWTError
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.config import get_settings
from app.database import get_db
from app.models.user import User

settings = get_settings()
security = HTTPBearer()

def apply_project_access_scope(query, user: User):
    """Scope projects to the authenticated account's organization."""
    from app.models.project import Project

    if user.organization_id is not None:
        return query.where(Project.organization_id == user.organization_id)

    return query.where(
        Project.organization_id.is_(None),
        Project.owner_id == user.id,
    )


def resolve_project_permission(
    project,
    user: User,
    explicit_permission: str | None = None,
) -> str | None:
    """Return full access for same-organization projects."""
    if user.organization_id is not None:
        return "admin" if project.organization_id == user.organization_id else None
    return (
        "admin"
        if project.organization_id is None and project.owner_id == user.id
        else None
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a password against a hash."""
    try:
        return bcrypt.checkpw(
            plain_password.encode("utf-8"),
            hashed_password.encode("utf-8"),
        )
    except (TypeError, ValueError):
        return False


def hash_password(password: str) -> str:
    """Hash a password."""
    return bcrypt.hashpw(
        password.encode("utf-8"),
        bcrypt.gensalt(),
    ).decode("utf-8")


def create_access_token(
    user_id: str,
    expires_delta: Optional[timedelta] = None,
) -> str:
    """Create a JWT access token."""
    expire = datetime.utcnow() + (
        expires_delta or timedelta(hours=settings.ACCESS_TOKEN_EXPIRE_HOURS)
    )
    payload = {
        "sub": user_id,
        "type": "access",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str) -> str:
    """Create a JWT refresh token."""
    expire = datetime.utcnow() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {
        "sub": user_id,
        "type": "refresh",
        "exp": expire,
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_token(token: str, token_type: str = "access") -> dict:
    """Verify and decode a JWT token."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != token_type:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        return payload
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
        )


def create_internal_token(
    scope: str = "processing_internal",
    *,
    subject: Optional[str] = None,
    expires_delta: Optional[timedelta] = None,
):
    """Create a short-lived JWT token for internal service calls."""
    expire = datetime.utcnow() + (
        expires_delta or timedelta(minutes=10)
    )
    payload = {
        "sub": subject or "system",
        "type": "internal",
        "scope": scope,
        "iat": datetime.utcnow(),
        "exp": expire,
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def verify_internal_token(token: str, *, required_scope: str | None = None) -> dict:
    """Verify an internal service token."""
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM]
        )
        if payload.get("type") != "internal":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid internal token type",
            )
        if required_scope and payload.get("scope") != required_scope:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid internal token scope",
            )
        return payload
    except PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired internal token",
        )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Get the current authenticated user from JWT token."""
    payload = verify_token(credentials.credentials, "access")
    user_id = payload.get("sub")
    
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )
    
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User account is disabled",
        )
    
    return user


class PermissionChecker:
    """Check organization-scoped project access.

    Permission names are retained for API compatibility, but the product has one
    operator account per organization, so view/edit/admin resolve identically.
    """

    def __init__(self, required_permission: str = "view"):
        self.required_permission = required_permission
    
    async def check(
        self,
        project_id: str,
        user: User,
        db: AsyncSession,
    ) -> bool:
        """Return True only for a project in the account's organization."""
        from app.models.project import Project

        result = await db.execute(
            select(Project).where(Project.id == project_id)
        )
        project = result.scalar_one_or_none()
        if project is None:
            return False
        return resolve_project_permission(project, user) == "admin"
