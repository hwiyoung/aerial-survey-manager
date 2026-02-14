"""Pydantic schemas for Project and related models."""
from datetime import datetime
from typing import Optional, List, Literal, Any
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
    source_deleted: bool = False
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
    # 현재 사용자 기준 권한(유효 권한)
    current_user_permission: Optional[str] = None  # view | edit | admin
    can_edit: bool = False
    can_delete: bool = False

    class Config:
        from_attributes = True


class ProjectListResponse(BaseModel):
    """Paginated project list response."""
    items: List[ProjectResponse]
    total: int
    page: int
    page_size: int


class ProjectBatchAction(BaseModel):
    """Batch operation request payload."""
    action: Literal["delete", "update_status"]
    project_ids: List[UUID] = Field(default_factory=list, min_length=1)
    status: Optional[str] = None


class ProjectBatchFailure(BaseModel):
    """Per-project error detail for batch operations."""
    project_id: UUID
    reason: str


class ProjectBatchResponse(BaseModel):
    """Batch operation result."""
    action: Literal["delete", "update_status"]
    requested: int
    succeeded: List[UUID] = Field(default_factory=list)
    failed: List[ProjectBatchFailure] = Field(default_factory=list)


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
    # Image dimensions
    image_width: Optional[int] = None  # pixels
    image_height: Optional[int] = None  # pixels
    # Camera model reference
    camera_model: Optional["CameraModelResponse"] = None
    exterior_orientation: Optional["EOData"] = None

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
    # Sensor size in pixels (image dimensions)
    sensor_width_px: Optional[int] = None  # pixels
    sensor_height_px: Optional[int] = None  # pixels
    # PPA (Principal Point of Autocollimation) offset
    ppa_x: Optional[float] = None  # mm
    ppa_y: Optional[float] = None  # mm

    class Config:
        from_attributes = True


# --- Processing Job Schemas ---
class ProcessingOptions(BaseModel):
    """Processing options schema."""
    engine: str = "metashape"
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
    metrics: Optional[dict[str, Any]] = None

    class Config:
        from_attributes = True


class ProcessingEnginePolicy(BaseModel):
    """Processing engine support/policy item."""

    name: str
    enabled: bool
    reason: Optional[str] = None
    queue_name: Optional[str] = None


class ProcessingEnginesResponse(BaseModel):
    """Available processing engines and policy summary."""

    engines: List[ProcessingEnginePolicy]
    default_engine: str


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


class StorageStatsResponse(BaseModel):
    """Per-directory storage statistics."""
    storage_size: int    # bytes - storage directory (local or MinIO)
    processing_size: int # bytes - processing data directory
    tiles_size: int      # bytes - offline tiles directory
    storage_backend: str = "minio"  # "local" or "minio"


class ProcessingMetricJobSummary(BaseModel):
    """Summary item for a single processing job metric."""
    project_id: UUID
    project_title: Optional[str] = None
    engine: Optional[str] = None
    status: str
    progress: int
    queue_wait_seconds: Optional[float] = None
    total_elapsed_seconds: Optional[float] = None
    memory_usage_mb: Optional[float] = None
    queue_wait_warn_seconds: Optional[float] = None
    total_elapsed_warn_seconds: Optional[float] = None
    memory_warn_mb: Optional[float] = None
    queue_wait_exceeded: bool = False
    total_elapsed_exceeded: bool = False
    memory_exceeded: bool = False


class ProcessingMetricsSummary(BaseModel):
    """Aggregate queue/processing metrics summary."""
    queue_wait_sample_count: int = 0
    queue_wait_avg_seconds: Optional[float] = None
    queue_wait_p95_seconds: Optional[float] = None
    queue_wait_violation_count: int = 0
    queue_wait_violation_rate: Optional[float] = None

    total_elapsed_sample_count: int = 0
    total_elapsed_avg_seconds: Optional[float] = None
    total_elapsed_p95_seconds: Optional[float] = None
    total_elapsed_violation_count: int = 0
    total_elapsed_violation_rate: Optional[float] = None

    memory_usage_sample_count: int = 0
    memory_usage_avg_mb: Optional[float] = None
    memory_usage_p95_mb: Optional[float] = None
    memory_violation_count: int = 0
    memory_violation_rate: Optional[float] = None


class ProcessingMetricsResponse(BaseModel):
    """Processing performance metrics response."""
    generated_at: datetime
    scope: str
    organization_id: Optional[UUID] = None
    total_jobs: int
    status_counts: dict[str, int] = Field(default_factory=dict)
    summary: ProcessingMetricsSummary
    recent_jobs: List[ProcessingMetricJobSummary] = Field(default_factory=list)
