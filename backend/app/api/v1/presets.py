"""Processing Presets API endpoints."""
from typing import Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete

from app.database import get_db
from app.models import User, ProcessingPreset
from app.schemas.preset import (
    PresetCreate,
    PresetUpdate,
    PresetResponse,
    PresetListResponse,
)
from app.auth.jwt import get_current_user

router = APIRouter(prefix="/presets", tags=["Processing Presets"])


@router.post("", response_model=PresetResponse, status_code=status.HTTP_201_CREATED)
async def create_preset(
    data: PresetCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Create a new processing preset.
    
    If is_default is True, any existing default preset will be unmarked.
    """
    # If setting as default, unmark existing defaults
    if data.is_default:
        await db.execute(
            update(ProcessingPreset)
            .where(ProcessingPreset.user_id == current_user.id)
            .where(ProcessingPreset.is_default == True)
            .values(is_default=False)
        )
    
    preset = ProcessingPreset(
        user_id=current_user.id,
        name=data.name,
        description=data.description,
        options=data.options.model_dump(),
        is_default=data.is_default,
    )
    
    db.add(preset)
    await db.commit()
    await db.refresh(preset)
    
    return preset


@router.get("", response_model=PresetListResponse)
async def list_presets(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    List all processing presets for the current user.
    
    Returns presets ordered by is_default (default first), then by name.
    """
    result = await db.execute(
        select(ProcessingPreset)
        .where(ProcessingPreset.user_id == current_user.id)
        .order_by(ProcessingPreset.is_default.desc(), ProcessingPreset.name)
    )
    presets = result.scalars().all()
    
    return PresetListResponse(items=presets, total=len(presets))


@router.get("/defaults", response_model=PresetListResponse)
async def get_default_presets(
    db: AsyncSession = Depends(get_db),
):
    """
    Get system default presets (available to all users).
    
    These are predefined presets that users can use as starting points.
    """
    # Return predefined presets (hardcoded for simplicity)
    default_presets = [
        {
            "id": "00000000-0000-0000-0000-000000000001",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "name": "표준 정사영상",
            "description": "일반적인 정사영상 생성 설정 (GSD 5cm)",
            "options": {"engine": "odm", "gsd": 5.0, "process_mode": "Normal", "output_crs": "EPSG:5186", "output_format": "GeoTiff"},
            "is_default": True,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
        {
            "id": "00000000-0000-0000-0000-000000000002",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "name": "고해상도 정사영상",
            "description": "고해상도 정사영상 생성 (GSD 2cm)",
            "options": {"engine": "odm", "gsd": 2.0, "process_mode": "High", "output_crs": "EPSG:5186", "output_format": "GeoTiff"},
            "is_default": False,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
        {
            "id": "00000000-0000-0000-0000-000000000003",
            "user_id": "00000000-0000-0000-0000-000000000000",
            "name": "빠른 미리보기",
            "description": "빠른 처리용 저해상도 설정 (GSD 10cm)",
            "options": {"engine": "odm", "gsd": 10.0, "process_mode": "Preview", "output_crs": "EPSG:5186", "output_format": "GeoTiff"},
            "is_default": False,
            "created_at": "2026-01-01T00:00:00",
            "updated_at": "2026-01-01T00:00:00",
        },
    ]
    
    return {"items": default_presets, "total": len(default_presets)}


@router.get("/{preset_id}", response_model=PresetResponse)
async def get_preset(
    preset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific preset by ID."""
    result = await db.execute(
        select(ProcessingPreset)
        .where(ProcessingPreset.id == preset_id)
        .where(ProcessingPreset.user_id == current_user.id)
    )
    preset = result.scalars().first()
    
    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preset not found"
        )
    
    return preset


@router.patch("/{preset_id}", response_model=PresetResponse)
async def update_preset(
    preset_id: UUID,
    data: PresetUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update an existing preset."""
    result = await db.execute(
        select(ProcessingPreset)
        .where(ProcessingPreset.id == preset_id)
        .where(ProcessingPreset.user_id == current_user.id)
    )
    preset = result.scalars().first()
    
    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preset not found"
        )
    
    # If setting as default, unmark existing defaults
    if data.is_default:
        await db.execute(
            update(ProcessingPreset)
            .where(ProcessingPreset.user_id == current_user.id)
            .where(ProcessingPreset.id != preset_id)
            .where(ProcessingPreset.is_default == True)
            .values(is_default=False)
        )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    if "options" in update_data and update_data["options"]:
        update_data["options"] = update_data["options"].model_dump() if hasattr(update_data["options"], "model_dump") else update_data["options"]
    
    for key, value in update_data.items():
        setattr(preset, key, value)
    
    await db.commit()
    await db.refresh(preset)
    
    return preset


@router.delete("/{preset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_preset(
    preset_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a preset."""
    result = await db.execute(
        select(ProcessingPreset)
        .where(ProcessingPreset.id == preset_id)
        .where(ProcessingPreset.user_id == current_user.id)
    )
    preset = result.scalars().first()
    
    if not preset:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Preset not found"
        )
    
    await db.delete(preset)
    await db.commit()
    
    return None
