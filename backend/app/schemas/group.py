"""Pydantic schemas for ProjectGroup."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class GroupBase(BaseModel):
    """Base group schema."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")  # Hex color


class GroupCreate(GroupBase):
    """Group creation schema."""
    parent_id: Optional[UUID] = None


class GroupUpdate(BaseModel):
    """Group update schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    parent_id: Optional[UUID] = None


class GroupResponse(GroupBase):
    """Group response schema."""
    id: UUID
    parent_id: Optional[UUID] = None
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    project_count: int = 0
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class GroupTreeNode(GroupResponse):
    """Group with children for tree structure."""
    children: List["GroupTreeNode"] = []
    
    class Config:
        from_attributes = True


class GroupListResponse(BaseModel):
    """Group list response with tree structure."""
    items: List[GroupTreeNode]
    total: int


# Update forward references
GroupTreeNode.model_rebuild()
