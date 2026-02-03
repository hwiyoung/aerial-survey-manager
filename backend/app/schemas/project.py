"""Pydantic schemas for Project and related models."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


# --- Project Schemas ---
class ProjectBase(BaseModel):
    """Base project schema."""
    title: str
    region: Optional[str] = None
    company: Optional[str] = None


class ProjectCreate(ProjectBase):
    """Project creation schema."""
    group_id: Optional[UUID] = None


class ProjectUpdate(BaseModel):
    """Project update schema."""
    title: Optional[str] = None
    region: Optional[str] = None
    company: Optional[str] = None
    status: Optional[str] = None
    group_id: Optional[UUID] = None


class ProjectResponse(ProjectBase):
    """Project response schema."""
    id: UUID
    status: str
    progress: int
    owner_id: Optional[UUID] = None
    organization_id: Optional[UUID] = None
    group_id: Optional[UUID] = None
    group_name: Optional[str] = None
    created_at: datetime
    updated_at: datetime
    image_count: int = 0
    source_size: Optional[int] = None
    ortho_size: Optional[int] = None
    area: Optional[float] = None
    ortho_path: Optional[str] = None
    bounds: Optional[List[List[float]]] = None  # List of [lat, lng] or [[lat, lng], ...]
    # 업로드 상태 통계
    upload_completed_count: int = 0  # 업로드 완료된 이미지 수
    upload_in_progress: bool = False  # 업로드 진행 중 여부
    # 처리 결과 정보
    result_gsd: Optional[float] = None  # 처리 결과 GSD (cm/pixel)
    process_mode: Optional[str] = None  # 마지막 처리 모드 (Preview, Normal, High)

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Paginated project list response."""
    items: List[ProjectResponse]
    total: int
    page: int
    page_size: int


# --- Image Schemas ---
class ImageBase(BaseModel):
    """Base image schema."""
    filename: str


class ImageResponse(ImageBase):
    """Image response schema."""
    id: UUID
    project_id: UUID
    original_path: Optional[str] = None
    thumbnail_path: Optional[str] = None
    thumbnail_url: Optional[str] = None
    captured_at: Optional[datetime] = None
    resolution: Optional[str] = None
    file_size: Optional[int] = None
    has_error: bool = False
    upload_status: str = "pending"
    created_at: datetime
    exterior_orientation: Optional["EOData"] = None  # Renamed from eo to avoid confusion? No, relationship is exterior_orientation
    
    class Config:
        from_attributes = True


class ImageUploadResponse(BaseModel):
    """Response after initiating image upload."""
    image_id: UUID
    upload_url: str  # tus upload URL
    upload_id: str


# --- EO Schemas ---
class EOData(BaseModel):
    """Single EO data point."""
    image_id: Optional[UUID] = None  # Changed from str to UUID to match model
    x: float
    y: float
    z: float
    omega: float = 0.0
    phi: float = 0.0
    kappa: float = 0.0
    crs: Optional[str] = None
    
    class Config:
        from_attributes = True


class EOConfig(BaseModel):
    """EO file parsing configuration."""
    delimiter: str = ","
    has_header: bool = Field(default=True, alias="hasHeader")
    crs: str = "EPSG:4326"
    columns: dict = Field(
        default={"image_name": 0, "x": 1, "y": 2, "z": 3, "omega": 4, "phi": 5, "kappa": 6}
    )

    class Config:
        populate_by_name = True


class EOUploadResponse(BaseModel):
    """EO upload response."""
    parsed_count: int
    matched_count: int
    errors: List[str] = []


# --- Camera Model Schemas ---
class CameraModelBase(BaseModel):
    """Base camera model schema."""
    name: str
    focal_length: Optional[float] = None
    sensor_width: Optional[float] = None
    sensor_height: Optional[float] = None
    pixel_size: Optional[float] = None


class CameraModelCreate(CameraModelBase):
    """Camera model creation schema."""
    is_custom: bool = True


class CameraModelResponse(CameraModelBase):
    """Camera model response schema."""
    id: UUID
    is_custom: bool
    
    class Config:
        from_attributes = True


# --- Processing Job Schemas ---
class ProcessingOptions(BaseModel):
    """Processing options schema."""
    engine: str = "metashape"  # metashape only (odm, external disabled)
    gsd: float = 5.0  # cm/pixel
    output_crs: str = "EPSG:5186"
    output_format: str = "GeoTiff"
    process_mode: str = "Normal"  # Preview, Normal, High (Metashape)
    # Advanced options
    build_point_cloud: bool = False  # Point cloud 생성 여부 (3D Tiles 출력 시 필요)


class ProcessingJobResponse(BaseModel):
    """Processing job response schema."""
    id: UUID
    project_id: UUID
    engine: str
    gsd: float
    output_crs: str
    output_format: str
    status: str
    progress: int
    message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    error_message: Optional[str] = None
    result_path: Optional[str] = None
    result_size: Optional[int] = None
    result_gsd: Optional[float] = None  # 처리 결과 GSD (cm/pixel)
    process_mode: Optional[str] = None  # Preview, Normal, High

    class Config:
        from_attributes = True


class ProcessingStatusUpdate(BaseModel):
    """WebSocket status update schema."""
    job_id: UUID
    status: str
    progress: int
    message: Optional[str] = None


# --- QC Schemas ---
class QCResultBase(BaseModel):
    """Base QC result schema."""
    issues: List[str] = []
    status: str = "pending"
    comment: Optional[str] = None


class QCResultUpdate(QCResultBase):
    """QC result update schema."""
    pass


class QCResultResponse(QCResultBase):
    """QC result response schema."""
    id: UUID
    image_id: UUID
    checked_by: Optional[UUID] = None
    checked_at: Optional[datetime] = None
    
    class Config:
        from_attributes = True


# --- Statistics Schemas ---
class MonthlyStats(BaseModel):
    """Monthly statistics item."""
    month: int  # 1-12
    year: int
    count: int  # Number of projects
    completed: int  # Completed projects
    processing: int  # Processing projects


class MonthlyStatsResponse(BaseModel):
    """Monthly statistics response."""
    year: int
    data: List[MonthlyStats]


class RegionalStats(BaseModel):
    """Regional statistics item."""
    region: str
    count: int
    percentage: float


class RegionalStatsResponse(BaseModel):
    """Regional statistics response."""
    total: int
    data: List[RegionalStats]
