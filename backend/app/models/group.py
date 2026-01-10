"""Project Group model for hierarchical project organization."""
import uuid
from datetime import datetime
from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class ProjectGroup(Base):
    """Hierarchical project group model."""
    
    __tablename__ = "project_groups"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    color: Mapped[str | None] = mapped_column(String(20), nullable=True)  # e.g., "#3b82f6"
    
    # Hierarchical structure (self-referencing FK)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("project_groups.id", ondelete="CASCADE"), nullable=True
    )
    
    # Owner and organization
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Relationships
    parent: Mapped["ProjectGroup | None"] = relationship(
        "ProjectGroup", 
        remote_side=[id], 
        back_populates="children"
    )
    children: Mapped[list["ProjectGroup"]] = relationship(
        "ProjectGroup", 
        back_populates="parent",
        cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", 
        back_populates="group"
    )
    owner: Mapped["User"] = relationship("User")
