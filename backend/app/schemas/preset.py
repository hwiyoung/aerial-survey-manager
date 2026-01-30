"""Pydantic schemas for Processing Presets."""
from datetime import datetime
from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field


class PresetOptionsSchema(BaseModel):
    """Processing options that can be saved in a preset."""
    engine: str = "odm"  # odm, external
    gsd: float = 5.0  # cm/pixel
    process_mode: str = "Normal"  # Preview, Normal, High (Metashape)
    output_crs: str = "EPSG:5186"
    output_format: str = "GeoTiff"


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
    id: UUID
    user_id: UUID
    options: PresetOptionsSchema
    is_default: bool
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class PresetListResponse(BaseModel):
    """List of presets response."""
    items: List[PresetResponse]
    total: int
