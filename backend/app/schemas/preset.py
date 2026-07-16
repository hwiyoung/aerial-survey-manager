"""Pydantic schemas for Processing Presets."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field


class PresetOptionsSchema(BaseModel):
    """Processing options that can be saved in a preset."""
    engine: str = "metashape"  # default GPU processing engine
    gsd: float = 5.0  # cm/pixel
    process_mode: str = "Normal"  # Preview, Normal, High
    output_crs: str = "EPSG:5186"
    output_format: str = "GeoTiff"
    eo_only_align: bool = True  # EO reference와 매칭된 이미지만 정합
    build_point_cloud: bool = False  # 포인트 클라우드 생성 여부


class PresetBase(BaseModel):
    """Base preset schema."""
    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = None


class PresetCreate(PresetBase):
    """Preset creation schema."""
    options: PresetOptionsSchema
    is_default: bool = False


class PresetUpdate(BaseModel):
    """Preset update schema."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = None
    options: Optional[PresetOptionsSchema] = None
    is_default: Optional[bool] = None


class PresetResponse(PresetBase):
    """Preset response schema."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    options: PresetOptionsSchema
    is_default: bool
    created_at: datetime
    updated_at: datetime
    
class PresetListResponse(BaseModel):
    """List of presets response."""
    items: List[PresetResponse]
    total: int
