"""Pydantic schemas for User and Auth."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


# --- Auth Schemas ---
class TokenResponse(BaseModel):
    """Token response schema."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Access token expiration in seconds")


class TokenRefreshRequest(BaseModel):
    """Refresh token request schema."""
    refresh_token: str


class LoginRequest(BaseModel):
    """Login request schema."""
    email: str  # username or email
    password: str


class UserBase(BaseModel):
    """Authenticated operator schema."""
    email: str
    name: Optional[str] = None


class UserResponse(UserBase):
    """Current account response schema."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
