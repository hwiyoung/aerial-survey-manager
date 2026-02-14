"""Camera model API endpoints."""
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.project import CameraModel
from app.schemas.project import CameraModelCreate, CameraModelResponse
from app.auth.jwt import get_current_user, is_admin_role

router = APIRouter(prefix="/camera-models", tags=["Camera Models"])


@router.get("", response_model=List[CameraModelResponse])
async def list_camera_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List available camera models."""
    query = select(CameraModel)
    
    # Filter by organization or public
    if not is_admin_role(current_user.role):
        query = query.where(
            (CameraModel.organization_id == current_user.organization_id) |
            (CameraModel.organization_id == None)
        )
    
    result = await db.execute(query)
    return result.scalars().all()


@router.post("", response_model=CameraModelResponse, status_code=status.HTTP_201_CREATED)
async def create_camera_model(
    data: CameraModelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new camera model."""
    camera_model = CameraModel(
        name=data.name,
        focal_length=data.focal_length,
        sensor_width=data.sensor_width,
        sensor_height=data.sensor_height,
        pixel_size=data.pixel_size,
        is_custom=data.is_custom,
        organization_id=current_user.organization_id if data.is_custom else None
    )
    db.add(camera_model)
    await db.commit()
    await db.refresh(camera_model)
    return camera_model


@router.delete("/{camera_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_camera_model(
    camera_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete a camera model."""
    result = await db.execute(select(CameraModel).where(CameraModel.id == camera_id))
    camera_model = result.scalar_one_or_none()
    
    if not camera_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera model not found",
        )
    
    # Permission check
    if not is_admin_role(current_user.role) and camera_model.organization_id != current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this camera model",
        )
    
    if not camera_model.is_custom and not is_admin_role(current_user.role):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can delete standard camera models",
        )
        
    await db.delete(camera_model)
    await db.commit()
