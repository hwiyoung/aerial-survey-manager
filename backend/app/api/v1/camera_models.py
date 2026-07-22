"""Camera model API endpoints."""
import asyncio
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.jwt import get_current_user
from app.database import get_db
from app.errors import AppError
from app.models.project import CameraModel, Image
from app.models.user import User
from app.schemas.project import CameraModelCreate, CameraModelResponse
from app.services.camera_models import (
    apply_camera_model_access_scope,
    camera_model_name_exists,
    can_manage_camera_model,
    custom_model_organization_id,
    normalize_camera_model_name,
)
from app.services.camera_io import (
    backup_and_replace_io,
    cleanup_io_backups,
    prepare_io_update,
    read_io_document,
    restore_io,
    sync_standard_camera_models,
)
from pydantic import BaseModel, Field

router = APIRouter(prefix="/camera-models", tags=["Camera Models"])
io_update_lock = asyncio.Lock()


class CameraIoUpdateRequest(BaseModel):
    content: str = Field(min_length=1, max_length=2_000_000)
    expected_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _organization_required_error(exc: ValueError) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=str(exc),
    )


async def _ensure_unique_name(
    db: AsyncSession,
    *,
    name: str,
    organization_id: UUID | None,
    exclude_id: UUID | None = None,
) -> None:
    if await camera_model_name_exists(
        db,
        name=name,
        organization_id=organization_id,
        exclude_id=exclude_id,
    ):
        scope = "public models" if organization_id is None else "your organization"
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A camera model with this name already exists in {scope}.",
        )


def _apply_camera_model_data(
    camera_model: CameraModel,
    data: CameraModelCreate,
) -> None:
    camera_model.name = normalize_camera_model_name(data.name)
    camera_model.focal_length = data.focal_length
    camera_model.sensor_width = data.sensor_width
    camera_model.sensor_height = data.sensor_height
    camera_model.pixel_size = data.pixel_size
    camera_model.sensor_width_px = data.sensor_width_px
    camera_model.sensor_height_px = data.sensor_height_px
    camera_model.ppa_x = data.ppa_x
    camera_model.ppa_y = data.ppa_y


async def _commit_camera_model(db: AsyncSession) -> None:
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A camera model with this name already exists in this sharing scope.",
        ) from exc


@router.get("", response_model=List[CameraModelResponse])
async def list_camera_models(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List available camera models."""
    query = select(CameraModel)
    query = apply_camera_model_access_scope(query, current_user)
    query = query.order_by(CameraModel.is_custom, func.lower(CameraModel.name))
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/io-config")
async def get_camera_io_config(
    _current_user: User = Depends(get_current_user),
):
    """Return the persistent standard IO document without exposing host paths."""
    try:
        return read_io_document()
    except ValueError as exc:
        raise AppError("CAMERA_IO_PARSE_FAILED", internal_detail=exc) from exc
    except OSError as exc:
        raise AppError("FILE_READ_FAILED", internal_detail=exc) from exc


@router.put("/io-config")
async def update_camera_io_config(
    request: CameraIoUpdateRequest,
    _current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Validate, back up, atomically save, and synchronize the standard IO catalog."""
    async with io_update_lock:
        try:
            prepared = prepare_io_update(request.content, request.expected_sha256)
        except FileExistsError as exc:
            raise AppError("RESOURCE_STATE_CONFLICT", internal_detail=exc) from exc
        except (UnicodeError, ValueError) as exc:
            raise AppError("CAMERA_IO_PARSE_FAILED", internal_detail=exc) from exc
        except OSError as exc:
            raise AppError("CAMERA_IO_SAVE_FAILED", internal_detail=exc) from exc

        try:
            backup_path = backup_and_replace_io(prepared)
        except OSError as exc:
            raise AppError("CAMERA_IO_SAVE_FAILED", internal_detail=exc) from exc

        try:
            sync_result = await sync_standard_camera_models(db, prepared["entries"])
            await db.commit()
        except Exception as exc:
            await db.rollback()
            try:
                restore_io(prepared)
            except OSError as restore_error:
                raise AppError(
                    "CAMERA_IO_SYNC_FAILED",
                    internal_detail={"sync": repr(exc), "restore": repr(restore_error)},
                ) from exc
            raise AppError("CAMERA_IO_SYNC_FAILED", internal_detail=exc) from exc

        try:
            cleanup_io_backups()
        except OSError:
            pass
        document = read_io_document()
        document.update(
            {
                "backup_created": backup_path.name,
                "sync": sync_result,
            }
        )
        return document


@router.post("", response_model=CameraModelResponse, status_code=status.HTTP_201_CREATED)
async def create_camera_model(
    data: CameraModelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create an organization-shared custom model."""
    is_custom = True
    try:
        organization_id = (
            custom_model_organization_id(current_user)
            if is_custom
            else None
        )
    except ValueError as exc:
        raise _organization_required_error(exc) from exc

    name = normalize_camera_model_name(data.name)
    await _ensure_unique_name(
        db,
        name=name,
        organization_id=organization_id,
    )

    camera_model = CameraModel(
        name=name,
        focal_length=data.focal_length,
        sensor_width=data.sensor_width,
        sensor_height=data.sensor_height,
        pixel_size=data.pixel_size,
        sensor_width_px=data.sensor_width_px,
        sensor_height_px=data.sensor_height_px,
        ppa_x=data.ppa_x,
        ppa_y=data.ppa_y,
        is_custom=is_custom,
        organization_id=organization_id,
    )
    db.add(camera_model)
    await _commit_camera_model(db)
    await db.refresh(camera_model)
    return camera_model


@router.put("/{camera_id}", response_model=CameraModelResponse)
async def update_camera_model(
    camera_id: UUID,
    data: CameraModelCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update a camera model."""
    result = await db.execute(select(CameraModel).where(CameraModel.id == camera_id))
    camera_model = result.scalar_one_or_none()

    if not camera_model:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera model not found",
        )

    if not can_manage_camera_model(camera_model, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to update this camera model",
        )

    is_custom = True
    try:
        organization_id = custom_model_organization_id(current_user)
    except ValueError as exc:
        raise _organization_required_error(exc) from exc

    name = normalize_camera_model_name(data.name)
    await _ensure_unique_name(
        db,
        name=name,
        organization_id=organization_id,
        exclude_id=camera_model.id,
    )

    _apply_camera_model_data(camera_model, data)
    camera_model.is_custom = is_custom
    camera_model.organization_id = organization_id

    await _commit_camera_model(db)
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
    
    if not can_manage_camera_model(camera_model, current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not authorized to delete this camera model",
        )

    await db.execute(
        update(Image)
        .where(Image.camera_model_id == camera_model.id)
        .values(camera_model_id=None)
    )
    await db.delete(camera_model)
    await db.commit()
