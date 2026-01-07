"""Project and related models."""
import uuid
from datetime import datetime
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, BigInteger
from sqlalchemy.dialects.postgresql import UUID, JSONB
from geoalchemy2 import Geometry
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Project(Base):
    """Main project model."""
    
    __tablename__ = "projects"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    region: Mapped[str | None] = mapped_column(String(100), nullable=True)
    company: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="pending")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    
    # Owner and organization
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )
    
    # Spatial data (PostGIS)
    bounds = mapped_column(Geometry("POLYGON", srid=4326), nullable=True)
    
    # Relationships
    owner: Mapped["User"] = relationship("User", back_populates="owned_projects")
    organization: Mapped["Organization"] = relationship("Organization", back_populates="projects")
    permissions: Mapped[list["ProjectPermission"]] = relationship(
        "ProjectPermission", back_populates="project", cascade="all, delete-orphan"
    )
    images: Mapped[list["Image"]] = relationship(
        "Image", back_populates="project", cascade="all, delete-orphan"
    )
    processing_jobs: Mapped[list["ProcessingJob"]] = relationship(
        "ProcessingJob", back_populates="project", cascade="all, delete-orphan"
    )


class Image(Base):
    """Aerial/Drone image model."""
    
    __tablename__ = "images"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    original_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    thumbnail_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(50), nullable=True)
    file_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    has_error: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    
    # Upload tracking (tus)
    upload_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, uploading, completed
    
    # Spatial data (PostGIS)
    location = mapped_column(Geometry("POINT", srid=4326), nullable=True)
    
    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="images")
    exterior_orientation: Mapped["ExteriorOrientation"] = relationship(
        "ExteriorOrientation", back_populates="image", uselist=False, cascade="all, delete-orphan"
    )
    qc_result: Mapped["QCResult"] = relationship(
        "QCResult", back_populates="image", uselist=False, cascade="all, delete-orphan"
    )


class ExteriorOrientation(Base):
    """Exterior Orientation (EO) data for images."""
    
    __tablename__ = "exterior_orientations"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), unique=True
    )
    x: Mapped[float] = mapped_column(Float, nullable=False)  # Longitude or Easting
    y: Mapped[float] = mapped_column(Float, nullable=False)  # Latitude or Northing
    z: Mapped[float] = mapped_column(Float, nullable=False)  # Altitude
    omega: Mapped[float] = mapped_column(Float, default=0.0)  # Roll
    phi: Mapped[float] = mapped_column(Float, default=0.0)    # Pitch
    kappa: Mapped[float] = mapped_column(Float, default=0.0)  # Yaw
    crs: Mapped[str] = mapped_column(String(50), default="EPSG:4326")
    
    # Relationships
    image: Mapped["Image"] = relationship("Image", back_populates="exterior_orientation")


class CameraModel(Base):
    """Camera model/Interior Orientation parameters."""
    
    __tablename__ = "camera_models"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    focal_length: Mapped[float | None] = mapped_column(Float, nullable=True)  # mm
    sensor_width: Mapped[float | None] = mapped_column(Float, nullable=True)  # mm
    sensor_height: Mapped[float | None] = mapped_column(Float, nullable=True)  # mm
    pixel_size: Mapped[float | None] = mapped_column(Float, nullable=True)  # µm
    is_custom: Mapped[bool] = mapped_column(Boolean, default=False)
    organization_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("organizations.id"), nullable=True
    )


class ProcessingJob(Base):
    """Processing job for orthophoto generation."""
    
    __tablename__ = "processing_jobs"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE")
    )
    engine: Mapped[str] = mapped_column(String(20), default="odm")  # odm, external
    gsd: Mapped[float] = mapped_column(Float, default=5.0)  # cm/pixel
    output_crs: Mapped[str] = mapped_column(String(50), default="EPSG:5186")
    output_format: Mapped[str] = mapped_column(String(20), default="GeoTiff")
    status: Mapped[str] = mapped_column(String(50), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    result_checksum: Mapped[str | None] = mapped_column(String(64), nullable=True)  # SHA256
    result_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    
    # Celery task tracking
    celery_task_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    
    # Relationships
    project: Mapped["Project"] = relationship("Project", back_populates="processing_jobs")


class QCResult(Base):
    """Quality Control result for images."""
    
    __tablename__ = "qc_results"
    
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("images.id", ondelete="CASCADE"), unique=True
    )
    issues: Mapped[dict] = mapped_column(JSONB, default=list)  # ['blur', 'overexposure', etc.]
    status: Mapped[str] = mapped_column(String(20), default="pending")  # pending, pass, fail
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    checked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    checked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    
    # Relationships
    image: Mapped["Image"] = relationship("Image", back_populates="qc_result")
