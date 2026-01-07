"""Pydantic schemas for User and Auth."""
from datetime import datetime
from typing import Optional
from uuid import UUID
from pydantic import BaseModel, EmailStr, Field


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
    email: EmailStr
    password: str


class RegisterRequest(BaseModel):
    """User registration request schema."""
    email: EmailStr
    password: str = Field(min_length=8)
    name: str = Field(min_length=1, max_length=100)
    organization_id: Optional[UUID] = None


# --- User Schemas ---
class UserBase(BaseModel):
    """Base user schema."""
    email: EmailStr
    name: Optional[str] = None
    role: str = "user"


class UserCreate(UserBase):
    """User creation schema."""
    password: str = Field(min_length=8)
    organization_id: Optional[UUID] = None


class UserUpdate(BaseModel):
    """User update schema."""
    name: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


class UserResponse(UserBase):
    """User response schema."""
    id: UUID
    organization_id: Optional[UUID] = None
    is_active: bool
    created_at: datetime
    last_login: Optional[datetime] = None
    
    class Config:
        from_attributes = True


class UserWithOrg(UserResponse):
    """User response with organization details."""
    organization_name: Optional[str] = None


# --- Organization Schemas ---
class OrganizationBase(BaseModel):
    """Base organization schema."""
    name: str


class OrganizationCreate(OrganizationBase):
    """Organization creation schema."""
    quota_storage_gb: int = 1000
    quota_projects: int = 100


class OrganizationResponse(OrganizationBase):
    """Organization response schema."""
    id: UUID
    quota_storage_gb: int
    quota_projects: int
    created_at: datetime
    
    class Config:
        from_attributes = True
