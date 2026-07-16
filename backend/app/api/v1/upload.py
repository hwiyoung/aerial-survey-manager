"""Upload API endpoints for local and S3 multipart uploads."""
import hashlib
import logging
import os
import shutil
import uuid as uuid_mod
from datetime import datetime
from uuid import UUID
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel, ConfigDict, Field

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image, ExteriorOrientation
from app.schemas.project import ImageResponse
from app.auth.jwt import (
    PermissionChecker,
    apply_project_access_scope,
    get_current_user,
)
from app.config import get_settings
from app.services.storage import get_storage
from app.services.asset_tokens import build_project_asset_url
from app.services.quota import ensure_organization_quota
from app.services.processing_lifecycle import processing_options_for_job
from app.services.camera_models import resolve_accessible_camera_model
from app.services.upload_sessions import (
    MAX_MULTIPART_PARTS,
    MAX_MULTIPART_PART_SIZE,
    MAX_UPLOAD_FILES_PER_REQUEST,
    MIN_MULTIPART_PART_SIZE,
    LocalUploadSession,
    UploadSessionError,
    expected_part_size,
    load_local_upload_session,
    multipart_part_count,
    nonreplaceable_upload_filenames,
    save_local_upload_session,
    validate_completed_part_numbers,
    validate_upload_batch,
)
from app.api.v1.filesystem import get_allowed_roots, is_within_allowed_root
from app.utils.storage_paths import (
    processing_metadata_path,
    source_image_key,
    source_thumbnail_key,
)

PROCESSING_ENGINE_QUEUE = os.getenv("PROCESSING_ENGINE_QUEUE", "gpu-engine")


def _processing_queue_name(engine_name: str | None) -> str:
    if not engine_name or engine_name == "metashape":
        return PROCESSING_ENGINE_QUEUE
    return engine_name


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/upload", tags=["Upload"])
settings = get_settings()


def _normalize_image_lookup_key(image_name: object) -> str:
    basename = os.path.basename(str(image_name or "").strip())
    return os.path.splitext(basename)[0].lower()


def _extract_metadata_crs(line: str) -> str | None:
    text = str(line or "").upper()
    if "EPSG" not in text:
        return None
    marker = text.split("EPSG", 1)[1]
    digits = "".join(ch for ch in marker if ch.isdigit())
    return f"EPSG:{digits}" if digits else None


def _read_source_eo_map(project_id: UUID) -> dict[str, dict]:
    """Read original EO coordinates from the processing metadata file."""
    metadata_path = processing_metadata_path(project_id)
    source_eo_by_key: dict[str, dict] = {}
    source_crs: str | None = None

    try:
        with open(metadata_path, "r", encoding="utf-8", errors="ignore") as f:
            for raw_line in f:
                line = raw_line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    source_crs = _extract_metadata_crs(line) or source_crs
                    continue

                parts = line.split()
                if len(parts) < 7:
                    continue

                image_name = " ".join(parts[:-6])
                try:
                    x_val, y_val, z_val, omega, phi, kappa = [float(value) for value in parts[-6:]]
                except ValueError:
                    continue

                source_eo_by_key[_normalize_image_lookup_key(image_name)] = {
                    "x": x_val,
                    "y": y_val,
                    "z": z_val,
                    "omega": omega,
                    "phi": phi,
                    "kappa": kappa,
                    "crs": source_crs,
                }
    except OSError:
        return {}

    return source_eo_by_key


async def _get_scoped_project(
    project_id: UUID,
    current_user: User,
    db: AsyncSession,
):
    query = select(Project).where(Project.id == project_id)
    query = apply_project_access_scope(query, current_user)
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _resolve_camera_model_id(
    camera_model_id: UUID | None,
    current_user: User,
    db: AsyncSession,
) -> UUID | None:
    if camera_model_id is None:
        return None

    camera_model = await resolve_accessible_camera_model(
        db,
        camera_model_id,
        current_user,
    )
    if camera_model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Camera model not found",
        )
    return camera_model.id


# Lazy import for MinIO-only service
def _get_s3_multipart_service():
    from app.services.s3_multipart import get_s3_multipart_service
    return get_s3_multipart_service()


@router.get("/projects/{project_id}/images", response_model=list[ImageResponse])
async def list_project_images(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all images for a project."""
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Image)
        .options(
            joinedload(Image.exterior_orientation),
            joinedload(Image.camera_model)
        )
        .where(Image.project_id == project_id)
        .order_by(Image.created_at)
    )
    images = result.scalars().unique().all()

    response = []
    source_eo_by_key = _read_source_eo_map(project_id)

    # Track images missing thumbnails for background regeneration
    missing_thumbnails = []

    for img in images:
        # Check if thumbnail is missing for completed uploads
        if not img.thumbnail_path and img.original_path and img.upload_status == "completed":
            missing_thumbnails.append(str(img.id))

        img_dict = {
            "id": img.id,
            "project_id": img.project_id,
            "filename": img.filename,
            "original_path": img.original_path,
            "thumbnail_path": img.thumbnail_path,
            "thumbnail_url": build_project_asset_url(
                img.project_id,
                img.thumbnail_path,
            ),
            "captured_at": img.captured_at,
            "resolution": img.resolution,
            "file_size": img.file_size,
            "has_error": img.has_error,
            "validation_status": img.validation_status,
            "validation_error": img.validation_error,
            "validated_at": img.validated_at,
            "upload_status": img.upload_status,
            "created_at": img.created_at,
            # Image dimensions
            "image_width": img.image_width,
            "image_height": img.image_height,
            # Camera model
            "camera_model": img.camera_model,
            "exterior_orientation": img.exterior_orientation,
            "source_exterior_orientation": source_eo_by_key.get(_normalize_image_lookup_key(img.filename)),
        }
        response.append(ImageResponse.model_validate(img_dict))

    # Trigger thumbnail regeneration for missing ones (in background)
    if missing_thumbnails:
        try:
            from app.workers.tasks import generate_thumbnail
            for image_id in missing_thumbnails[:10]:  # Limit to 10 at a time
                generate_thumbnail.delay(image_id)
            print(f"Triggered thumbnail generation for {len(missing_thumbnails)} images in project {project_id}")
        except Exception as e:
            print(f"Failed to trigger thumbnail regeneration: {e}")

    return response


# ============================================================================
# Local Path Import - Register images by local filesystem path (no file copy)
# ============================================================================

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".tif", ".tiff", ".png"}


class LocalImportRequest(BaseModel):
    """Request body for local path import."""
    model_config = ConfigDict(extra="forbid")

    source_dir: str
    file_paths: Optional[List[str]] = None  # Specific files to register (individual selection mode)
    camera_model_id: Optional[UUID] = None  # Optional accessible camera model


class LocalImportResponse(BaseModel):
    """Response for local path import."""
    registered: int
    skipped: int
    total_size: int
    invalid_files: List[dict] = Field(default_factory=list)


@router.post("/projects/{project_id}/local-import", response_model=LocalImportResponse)
async def local_import(
    project_id: UUID,
    request: LocalImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Register local image files by scanning a directory path.

    Instead of uploading files via HTTP, this endpoint scans a local directory
    for image files and creates Image records pointing to the original paths.
    No files are copied or moved.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Basic path validation: require absolute path with no traversal components
    raw_path = request.source_dir
    if not raw_path.startswith("/"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_dir must be an absolute path (starting with /)",
        )
    source_dir = Path(raw_path).resolve()
    if ".." in Path(raw_path).parts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="source_dir must not contain '..' components",
        )
    if not is_within_allowed_root(str(source_dir)):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: source_dir is outside allowed directories ({', '.join(get_allowed_roots())})",
        )

    logger.info(f"[local-import] Scanning directory: {source_dir} (raw={raw_path})")

    if not source_dir.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Directory not found: {request.source_dir}",
        )

    # 파일 스캔 + 사이즈 조회를 스레드풀에서 실행 (이벤트 루프 블로킹 방지)
    import asyncio

    def _scan_and_stat_files():
        """동기 파일시스템 작업을 별도 스레드에서 실행."""
        files = []
        if request.file_paths:
            for fp in request.file_paths:
                raw_file_path = Path(fp)
                if ".." in raw_file_path.parts:
                    continue
                if not raw_file_path.is_absolute():
                    continue
                p = raw_file_path.resolve()
                if not is_within_allowed_root(str(p)):
                    continue
                if p != source_dir and source_dir not in p.parents:
                    continue
                if p.is_file() and p.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        size = os.path.getsize(p)
                        files.append((p, size))
                    except OSError:
                        pass
        else:
            for entry in sorted(source_dir.iterdir()):
                if entry.is_file() and entry.suffix.lower() in IMAGE_EXTENSIONS:
                    try:
                        size = os.path.getsize(entry)
                        files.append((entry, size))
                    except OSError:
                        pass
        return files

    scanned_files = await asyncio.to_thread(_scan_and_stat_files)

    if not scanned_files:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No image files found in {request.source_dir} (supported: {', '.join(IMAGE_EXTENSIONS)})",
        )

    # Check for existing images to avoid duplicates
    filenames = [f[0].name for f in scanned_files]
    existing_result = await db.execute(
        select(Image.filename).where(
            Image.project_id == project_id,
            Image.filename.in_(filenames),
        )
    )
    existing_filenames = {row[0] for row in existing_result.all()}

    camera_model_id = await _resolve_camera_model_id(
        request.camera_model_id,
        current_user,
        db,
    )

    registered = 0
    skipped = 0
    total_size = 0
    invalid_files = []
    registered_filenames = []
    additional_storage_bytes = sum(
        file_size
        for file_path, file_size in scanned_files
        if file_path.name not in existing_filenames
    )
    await ensure_organization_quota(
        db,
        current_user.organization_id,
        additional_storage_bytes=additional_storage_bytes,
    )

    for file_path, file_size in scanned_files:
        if file_path.name in existing_filenames:
            skipped += 1
            continue

        image = Image(
            project_id=project_id,
            filename=file_path.name,
            original_path=str(file_path.resolve()),
            file_size=file_size,
            upload_status="completed",
            camera_model_id=camera_model_id,
        )
        image.validation_status = "unchecked"
        image.validation_error = None
        image.validated_at = None
        image.has_error = False
        db.add(image)
        registered += 1
        registered_filenames.append(file_path.name)
        total_size += file_size

    await db.commit()

    # Trigger thumbnail generation for newly registered images
    if registered > 0:
        try:
            # Re-query to get the image IDs we just created
            new_images_result = await db.execute(
                select(Image.id).where(
                    Image.project_id == project_id,
                    Image.filename.in_(registered_filenames),
                    Image.upload_status == "completed",
                )
            )
            from app.workers.tasks import generate_thumbnail
            for row in new_images_result.all():
                generate_thumbnail.delay(str(row[0]))
        except Exception as e:
            logger.warning(f"Failed to trigger thumbnail generation: {e}")

    logger.info(
        f"[local-import] project={project_id}, registered={registered}, "
        f"skipped={skipped}, invalid={len(invalid_files)}, total_size={total_size}"
    )

    return LocalImportResponse(
        registered=registered,
        skipped=skipped,
        total_size=total_size,
        invalid_files=invalid_files,
    )


@router.post("/projects/{project_id}/images/regenerate-thumbnails")
async def regenerate_project_thumbnails(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate thumbnails for all images in a project that are missing them."""
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    try:
        from app.workers.tasks import regenerate_missing_thumbnails
        task = regenerate_missing_thumbnails.delay(str(project_id))
        return {
            "status": "triggered",
            "task_id": task.id,
            "message": f"Thumbnail regeneration started for project {project_id}",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger thumbnail regeneration: {str(e)}",
        )


@router.get("/images/{image_id}", response_model=ImageResponse)
async def get_image(
    image_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a single image with thumbnail_url."""
    from sqlalchemy.orm import joinedload

    result = await db.execute(
        select(Image)
        .options(
            joinedload(Image.exterior_orientation),
            joinedload(Image.camera_model),
        )
        .where(Image.id == image_id)
    )
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    scoped_project = await _get_scoped_project(image.project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    source_eo_by_key = _read_source_eo_map(image.project_id)
    img_dict = {
        "id": image.id,
        "project_id": image.project_id,
        "filename": image.filename,
        "original_path": image.original_path,
        "thumbnail_path": image.thumbnail_path,
        "thumbnail_url": build_project_asset_url(
            image.project_id,
            image.thumbnail_path,
        ),
        "captured_at": image.captured_at,
        "resolution": image.resolution,
        "file_size": image.file_size,
        "has_error": image.has_error,
        "validation_status": image.validation_status,
        "validation_error": image.validation_error,
        "validated_at": image.validated_at,
        "upload_status": image.upload_status,
        "created_at": image.created_at,
        "image_width": image.image_width,
        "image_height": image.image_height,
        "camera_model": image.camera_model,
        "exterior_orientation": image.exterior_orientation,
        "source_exterior_orientation": source_eo_by_key.get(_normalize_image_lookup_key(image.filename)),
    }
    return ImageResponse.model_validate(img_dict)


@router.post("/images/{image_id}/regenerate-thumbnail")
async def regenerate_image_thumbnail(
    image_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """온디맨드 썸네일 생성 (API에서 직접 실행, URL 즉시 반환)."""
    import asyncio
    from sqlalchemy import update as sa_update
    from app.workers.tasks import _generate_thumbnail_gdal, _generate_thumbnail_pil

    result = await db.execute(select(Image).where(Image.id == image_id))
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Image not found")

    scoped_project = await _get_scoped_project(image.project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")

    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(image.project_id), current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    storage = get_storage()

    # 원본 파일 경로 결정
    if os.path.isabs(image.original_path) and os.path.exists(image.original_path):
        source_path = image.original_path
    else:
        local_src = storage.get_local_path(image.original_path)
        if local_src and os.path.exists(local_src):
            source_path = local_src
        else:
            # 로컬 접근 불가 → Celery 폴백
            from app.workers.tasks import generate_thumbnail
            task = generate_thumbnail.delay(str(image_id), force=True)
            return {"status": "triggered", "task_id": task.id}

    thumb_path = f"/tmp/thumb_{image_id}_{image.filename}.jpg"
    thumb_object_name = source_thumbnail_key(image.project_id, image.filename)

    def _run_generation():
        try:
            _generate_thumbnail_gdal(source_path, thumb_path)
        except Exception:
            _generate_thumbnail_pil(source_path, thumb_path)
        storage.upload_file(thumb_path, thumb_object_name, "image/jpeg")
        if os.path.exists(thumb_path):
            try:
                os.remove(thumb_path)
            except Exception:
                pass

    try:
        await asyncio.to_thread(_run_generation)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"썸네일 생성 실패: {str(e)}",
        )

    await db.execute(
        sa_update(Image).where(Image.id == image_id).values(thumbnail_path=thumb_object_name)
    )
    await db.commit()

    thumbnail_url = build_project_asset_url(image.project_id, thumb_object_name)
    return {"status": "completed", "thumbnail_url": thumbnail_url}


# ============================================================================
# S3 Multipart Upload API - High-performance direct upload to MinIO
# ============================================================================

class FileInfo(BaseModel):
    """File information for multipart upload initialization."""
    filename: str = Field(min_length=1, max_length=255)
    size: int = Field(gt=0)
    content_type: Optional[str] = "application/octet-stream"


class MultipartInitRequest(BaseModel):
    """Request body for multipart upload initialization."""
    model_config = ConfigDict(extra="forbid")

    files: List[FileInfo] = Field(
        min_length=1,
        max_length=MAX_UPLOAD_FILES_PER_REQUEST,
    )
    part_size: int = Field(
        default=10 * 1024 * 1024,
        ge=MIN_MULTIPART_PART_SIZE,
        le=MAX_MULTIPART_PART_SIZE,
    )
    camera_model_id: Optional[UUID] = None  # Link images to an accessible model


class PartInfo(BaseModel):
    """Part information with presigned URL."""
    part_number: int
    presigned_url: str
    start: int
    end: int
    size: int


class UploadInfo(BaseModel):
    """Upload information for a single file."""
    filename: str
    image_id: UUID
    upload_id: str
    object_key: str
    parts: List[PartInfo]


class MultipartInitResponse(BaseModel):
    """Response for multipart upload initialization."""
    uploads: List[UploadInfo]


class CompletedPart(BaseModel):
    """Completed part information."""
    part_number: int = Field(ge=1, le=MAX_MULTIPART_PARTS)
    etag: str = Field(min_length=1, max_length=512)


class CompletedUpload(BaseModel):
    """Completed upload information."""
    filename: str = Field(min_length=1, max_length=255)
    upload_id: str = Field(min_length=1, max_length=255)
    object_key: str = Field(min_length=1, max_length=1024)
    parts: List[CompletedPart] = Field(min_length=1, max_length=MAX_MULTIPART_PARTS)


class MultipartCompleteRequest(BaseModel):
    """Request body for completing multipart uploads."""
    uploads: List[CompletedUpload] = Field(
        min_length=1,
        max_length=MAX_UPLOAD_FILES_PER_REQUEST,
    )


class CompletedFileInfo(BaseModel):
    """Information about a completed file."""
    filename: str
    image_id: UUID
    status: str


class ExcludedFileInfo(BaseModel):
    """Information about a file uploaded but excluded from processing."""
    filename: str
    image_id: Optional[UUID] = None
    status: str = "excluded"
    reason: str
    error: str
    validation_status: Optional[str] = None
    details: List[str] = Field(default_factory=list)


class MultipartCompleteResponse(BaseModel):
    """Response for multipart upload completion."""
    completed: List[CompletedFileInfo]
    failed: List[dict]
    excluded: List[ExcludedFileInfo] = Field(default_factory=list)


class AbortUpload(BaseModel):
    """Upload to abort."""
    filename: str = Field(min_length=1, max_length=255)
    upload_id: str = Field(min_length=1, max_length=255)
    object_key: str = Field(min_length=1, max_length=1024)


class MultipartAbortRequest(BaseModel):
    """Request body for aborting multipart uploads."""
    uploads: List[AbortUpload] = Field(
        min_length=1,
        max_length=MAX_UPLOAD_FILES_PER_REQUEST,
    )


@router.post("/projects/{project_id}/multipart/init", response_model=MultipartInitResponse)
async def init_multipart_upload(
    project_id: UUID,
    request: MultipartInitRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initialize S3 multipart uploads for multiple files.

    Returns presigned URLs for each part of each file.
    Files are uploaded directly to MinIO from the browser.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Serialize filename allocation per project. The DB unique constraint remains
    # the final guard against concurrent requests from multiple API processes.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_key))"),
        {"lock_key": f"multipart-init:{project_id}"},
    )

    try:
        safe_filenames = validate_upload_batch(
            request.files,
            request.part_size,
            max_file_size=settings.MAX_UPLOAD_SIZE_GB * 1024 * 1024 * 1024,
        )
    except UploadSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    for file_info, safe_filename in zip(request.files, safe_filenames):
        file_info.filename = safe_filename

    existing_result = await db.execute(
        select(Image.filename, Image.file_size, Image.upload_status)
        .where(
            Image.project_id == project_id,
            Image.filename.in_(safe_filenames),
        )
    )
    existing_rows = existing_result.all()
    completed_conflicts = nonreplaceable_upload_filenames(existing_rows)
    if completed_conflicts:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": (
                    "Files that already completed upload cannot be replaced in place. "
                    "Delete the existing source images or rename the files first."
                ),
                "filenames": completed_conflicts,
            },
        )

    existing_sizes = {row.filename: row.file_size or 0 for row in existing_rows}

    cumulative_sizes = {}
    total_additional_bytes = 0
    for file_info in request.files:
        prev_size = cumulative_sizes.get(file_info.filename, existing_sizes.get(file_info.filename, 0))
        if file_info.size > prev_size:
            total_additional_bytes += file_info.size - prev_size
        cumulative_sizes[file_info.filename] = file_info.size

    await ensure_organization_quota(
        db,
        current_user.organization_id,
        additional_storage_bytes=total_additional_bytes,
    )

    uploads = []
    existing_image_rows = await db.execute(
        select(Image)
        .where(
            Image.project_id == project_id,
            Image.filename.in_(safe_filenames),
        )
        .with_for_update()
    )
    existing_images = {img.filename: img for img in existing_image_rows.scalars().all()}

    camera_model_id = await _resolve_camera_model_id(
        request.camera_model_id,
        current_user,
        db,
    )

    is_local = settings.STORAGE_BACKEND == "local"

    # Only initialize S3 service when in MinIO mode
    s3_service = None if is_local else _get_s3_multipart_service()

    for file_info in request.files:
        # Create or update image record
        existing_image = existing_images.get(file_info.filename)

        if existing_image:
            previous_upload_id = existing_image.upload_id
            if previous_upload_id and existing_image.upload_status == "uploading":
                if is_local:
                    try:
                        uuid_mod.UUID(previous_upload_id)
                    except ValueError:
                        pass
                    else:
                        old_staging_dir = (
                            Path(settings.LOCAL_STORAGE_PATH)
                            / ".uploads"
                            / previous_upload_id
                        )
                        shutil.rmtree(old_staging_dir, ignore_errors=True)
                else:
                    try:
                        s3_service.abort_multipart_upload(
                            object_key=source_image_key(project_id, file_info.filename),
                            upload_id=previous_upload_id,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to abort superseded multipart upload %s: %s",
                            previous_upload_id,
                            exc,
                        )
            existing_image.upload_status = "uploading"
            existing_image.file_size = file_info.size
            if camera_model_id:
                existing_image.camera_model_id = camera_model_id
            await db.flush()
            image = existing_image
        else:
            image = Image(
                project_id=project_id,
                filename=file_info.filename,
                file_size=file_info.size,
                upload_status="uploading",
                camera_model_id=camera_model_id,
            )
            db.add(image)
            await db.flush()

        # Generate object key
        object_key = source_image_key(project_id, file_info.filename)

        if is_local:
            # Local mode: generate API URLs for chunk upload
            upload_id = str(uuid_mod.uuid4())
            part_size = request.part_size
            parts = []
            part_number = 1
            offset = 0
            while offset < file_info.size:
                end = min(offset + part_size, file_info.size) - 1
                url = f"/api/v1/upload/projects/{project_id}/local/chunk?upload_id={upload_id}&part={part_number}"
                parts.append(PartInfo(
                    part_number=part_number,
                    presigned_url=url,
                    start=offset,
                    end=end,
                    size=end - offset + 1,
                ))
                offset += part_size
                part_number += 1

            staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload_id
            save_local_upload_session(
                staging_dir,
                LocalUploadSession(
                    upload_id=upload_id,
                    project_id=str(project_id),
                    image_id=str(image.id),
                    filename=file_info.filename,
                    object_key=object_key,
                    file_size=file_info.size,
                    part_size=part_size,
                    part_count=multipart_part_count(file_info.size, part_size),
                ),
            )
        else:
            # MinIO mode: use S3 multipart upload
            upload_id = s3_service.create_multipart_upload(
                object_key=object_key,
                content_type=file_info.content_type
            )
            raw_parts = s3_service.generate_part_presigned_urls(
                object_key=object_key,
                upload_id=upload_id,
                file_size=file_info.size,
                part_size=request.part_size
            )
            parts = [PartInfo(**p) for p in raw_parts]

        # Bind all subsequent chunk/complete/abort requests to this DB record.
        image.upload_id = upload_id

        uploads.append(UploadInfo(
            filename=file_info.filename,
            image_id=image.id,
            upload_id=upload_id,
            object_key=object_key,
            parts=parts,
        ))

    await db.commit()

    return MultipartInitResponse(uploads=uploads)


@router.post("/projects/{project_id}/multipart/complete", response_model=MultipartCompleteResponse)
async def complete_multipart_upload(
    project_id: UUID,
    request: MultipartCompleteRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Complete S3 multipart uploads and update image records.

    Called after all parts have been uploaded successfully.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    is_local = settings.STORAGE_BACKEND == "local"
    s3_service = None if is_local else _get_s3_multipart_service()
    storage = get_storage()
    completed = []
    failed = []
    excluded = []
    thumbnail_image_ids = []
    completed_staging_dirs: list[Path] = []

    logger.info(f"[complete] project={project_id}, uploads={len(request.uploads)}, is_local={is_local}")

    for upload in request.uploads:
        image = None
        savepoint = None
        completed_staging_dir = None
        try:
            # Isolate each file so one database/constraint failure does not poison
            # the transaction for every other file in the same completion request.
            savepoint = await db.begin_nested()
            logger.info(f"[complete] Processing: filename={upload.filename}, upload_id={upload.upload_id}, object_key={upload.object_key}")

            validate_completed_part_numbers(part.part_number for part in upload.parts)

            # A client may only complete the exact upload session allocated by init.
            image_result = await db.execute(
                select(Image)
                .where(
                    Image.project_id == project_id,
                    Image.upload_id == upload.upload_id,
                    Image.upload_status == "uploading",
                )
                .with_for_update()
            )
            bound_images = image_result.scalars().all()
            if len(bound_images) != 1:
                raise UploadSessionError("Upload session is not active for this project.")
            image = bound_images[0]

            expected_object_key = source_image_key(project_id, image.filename)
            if upload.filename != image.filename or upload.object_key != expected_object_key:
                raise UploadSessionError(
                    "Upload filename or object key does not match the initialized session."
                )

            if is_local:
                # Local upload IDs are UUIDs and map to a server-created metadata file.
                try:
                    uuid_mod.UUID(upload.upload_id)
                except ValueError as exc:
                    raise UploadSessionError("Invalid local upload ID.") from exc

                staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload.upload_id
                session = load_local_upload_session(staging_dir)
                if (
                    session.upload_id != upload.upload_id
                    or session.project_id != str(project_id)
                    or session.image_id != str(image.id)
                    or session.filename != image.filename
                    or session.object_key != expected_object_key
                    or session.file_size != image.file_size
                ):
                    raise UploadSessionError("Upload session metadata does not match the database.")

                completed_part_numbers = validate_completed_part_numbers(
                    part.part_number for part in upload.parts
                )
                if completed_part_numbers != list(range(1, session.part_count + 1)):
                    raise UploadSessionError("Not all expected upload parts were completed.")

                expected_part_paths = [
                    staging_dir / f"part_{part_number}"
                    for part_number in range(1, session.part_count + 1)
                ]
                expected_names = {path.name for path in expected_part_paths}
                unexpected_parts = [
                    path.name
                    for path in staging_dir.glob("part_*")
                    if path.name not in expected_names
                ]
                if unexpected_parts:
                    raise UploadSessionError("Unexpected files exist in the upload session.")

                for part_number, part_path in enumerate(expected_part_paths, start=1):
                    if not part_path.is_file():
                        raise UploadSessionError(f"Upload part {part_number} is missing.")
                    actual_part_size = part_path.stat().st_size
                    required_part_size = expected_part_size(
                        session.file_size,
                        session.part_size,
                        part_number,
                    )
                    if actual_part_size != required_part_size:
                        raise UploadSessionError(
                            f"Upload part {part_number} has an invalid size."
                        )

                # Merge into a sibling temporary file, then replace atomically.
                final_path = Path(storage.get_local_path(expected_object_key))
                final_path.parent.mkdir(parents=True, exist_ok=True)
                temporary_path = final_path.with_name(
                    f".{final_path.name}.{upload.upload_id}.tmp"
                )
                temporary_path.unlink(missing_ok=True)
                try:
                    with open(temporary_path, "wb") as out_f:
                        for part_path in expected_part_paths:
                            with open(part_path, "rb") as in_f:
                                shutil.copyfileobj(in_f, out_f)
                    actual_size = temporary_path.stat().st_size
                    if actual_size != session.file_size:
                        raise UploadSessionError("Merged upload size does not match initialization.")
                    temporary_path.replace(final_path)
                finally:
                    temporary_path.unlink(missing_ok=True)

                completed_staging_dir = staging_dir
            else:
                # MinIO mode: complete S3 multipart upload
                s3_service.complete_multipart_upload(
                    object_key=expected_object_key,
                    upload_id=upload.upload_id,
                    parts=[{"part_number": p.part_number, "etag": p.etag} for p in upload.parts]
                )
                actual_size = storage.get_object_size(expected_object_key)
                if actual_size != image.file_size:
                    storage.delete_object(expected_object_key)
                    raise UploadSessionError(
                        "Completed object size does not match initialization."
                    )

            image.original_path = expected_object_key
            image.file_size = actual_size
            image.upload_status = "completed"
            image.validation_status = "unchecked"
            image.validation_error = None
            image.validated_at = None
            image.has_error = False

            # Force database errors to occur inside this file's savepoint.
            await db.flush()
            await savepoint.commit()

            if completed_staging_dir is not None:
                completed_staging_dirs.append(completed_staging_dir)

            logger.info(f"[complete] Image updated: id={image.id}, filename={upload.filename} -> completed")

            completed.append(CompletedFileInfo(
                filename=upload.filename,
                image_id=image.id,
                status="completed"
            ))
            thumbnail_image_ids.append(str(image.id))

        except Exception as e:
            if savepoint is not None and savepoint.is_active:
                try:
                    await savepoint.rollback()
                except Exception:
                    logger.exception(
                        "[complete] Failed to roll back upload savepoint for %s",
                        upload.filename,
                    )
                    raise
            logger.error(f"[complete] Exception for {upload.filename}: {e}", exc_info=True)
            failed.append({
                "filename": upload.filename,
                "error": str(e)
            })

    await db.commit()

    # Keep staging data until the database commit succeeds so a failed commit can retry.
    for staging_dir in completed_staging_dirs:
        shutil.rmtree(staging_dir, ignore_errors=True)

    for image_id in thumbnail_image_ids:
        try:
            from app.workers.tasks import generate_thumbnail
            generate_thumbnail.delay(image_id)
        except Exception as e:
            logger.warning(f"Failed to trigger thumbnail task: {e}")

    logger.info(f"[complete] Done: completed={len(completed)}, failed={len(failed)}, excluded={len(excluded)}")
    if failed:
        logger.warning(f"[complete] Failed uploads: {failed}")
    if excluded:
        logger.warning(f"[complete] Excluded uploads: {excluded}")

    # --- Scheduled processing trigger hook ---
    # Check if this project has a scheduled processing job and all images are now uploaded
    if completed:
        try:
            from app.models.project import ProcessingJob
            from sqlalchemy import func

            # Serialize this hook with manual start/schedule/cancel requests.
            project_lock_result = await db.execute(
                select(Project)
                .where(Project.id == project_id)
                .with_for_update()
            )
            locked_project = project_lock_result.scalar_one_or_none()
            if not locked_project:
                return MultipartCompleteResponse(
                    completed=completed,
                    failed=failed,
                    excluded=excluded,
                )
            scoped_project = locked_project

            # Check for a scheduled job
            sched_result = await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.status == "scheduled",
                ).with_for_update()
            )
            scheduled_job = sched_result.scalar_one_or_none()

            if scheduled_job:
                # Count image upload statuses
                status_result = await db.execute(
                    select(
                        Image.upload_status,
                        func.count(Image.id).label("cnt"),
                    )
                    .where(Image.project_id == project_id)
                    .group_by(Image.upload_status)
                )
                status_counts = {row.upload_status: row.cnt for row in status_result}
                pending_or_uploading = status_counts.get("pending", 0) + status_counts.get("uploading", 0)
                completed_images = status_counts.get("completed", 0)
                failed_images = status_counts.get("failed", 0)

                logger.info(
                    f"[Scheduled Processing] Upload status for project {project_id}: "
                    f"completed={completed_images}, pending/uploading={pending_or_uploading}, failed={failed_images}"
                )

                if pending_or_uploading == 0 and completed_images > 0 and failed_images == 0:
                    eo_result = await db.execute(
                        select(func.count(ExteriorOrientation.id))
                        .join(Image, ExteriorOrientation.image_id == Image.id)
                        .where(
                            Image.project_id == project_id,
                            Image.upload_status == "completed",
                        )
                    )
                    eo_count = eo_result.scalar() or 0
                    metadata_path = processing_metadata_path(project_id)
                    if eo_count == 0 or not metadata_path.exists():
                        reason = (
                            "처리에 필요한 이미지와 EO 매칭 정보를 다시 확인해야 합니다."
                            if eo_count > 0
                            else "처리에 필요한 이미지와 EO 매칭 정보가 없습니다."
                        )
                        scheduled_job.status = "failed"
                        scheduled_job.error_message = reason
                        scoped_project.status = "error"
                        await db.commit()
                        logger.warning(
                            f"[Scheduled Processing] Blocked for project {project_id}: "
                            f"eo_count={eo_count}, metadata_exists={metadata_path.exists()}"
                        )
                        return MultipartCompleteResponse(completed=completed, failed=failed, excluded=excluded)

                    # All images uploaded — update DB state first (atomic)
                    scheduled_job.status = "queued"
                    scheduled_job.queued_at = datetime.utcnow()
                    scheduled_job.celery_task_id = str(uuid_mod.uuid4())
                    scoped_project.status = "queued"
                    scoped_project.progress = 0

                    options_dict = processing_options_for_job(scheduled_job)
                    queue_name = _processing_queue_name(scheduled_job.engine)

                    # Commit DB changes BEFORE submitting to Celery
                    await db.commit()

                    # Now submit Celery task — DB is already consistent
                    try:
                        from app.workers.tasks import process_orthophoto
                        process_orthophoto.apply_async(
                            args=[str(scheduled_job.id), str(project_id), options_dict],
                            queue=queue_name,
                            task_id=scheduled_job.celery_task_id,
                        )
                        print(f"[Scheduled Processing] Auto-triggered for project {project_id}, job {scheduled_job.id}")
                    except Exception as celery_err:
                        # Celery submission failed — revert DB state
                        print(f"[Scheduled Processing] Celery submission failed: {celery_err}")
                        scheduled_job.status = "scheduled"
                        scheduled_job.queued_at = None
                        scheduled_job.celery_task_id = None
                        scoped_project.status = "scheduled"
                        await db.commit()
        except Exception as e:
            # Don't fail the upload completion if the trigger fails
            print(f"[Scheduled Processing] Trigger check failed: {e}")

    return MultipartCompleteResponse(completed=completed, failed=failed, excluded=excluded)


@router.post("/projects/{project_id}/multipart/abort")
async def abort_multipart_upload(
    project_id: UUID,
    request: MultipartAbortRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Abort/cancel S3 multipart uploads.

    Cleans up incomplete uploads and marks images as failed.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    is_local = settings.STORAGE_BACKEND == "local"
    s3_service = None if is_local else _get_s3_multipart_service()
    aborted = []
    errors = []

    for upload in request.uploads:
        try:
            result = await db.execute(
                select(Image)
                .where(
                    Image.project_id == project_id,
                    Image.upload_id == upload.upload_id,
                    Image.upload_status == "uploading",
                )
                .with_for_update()
            )
            bound_images = result.scalars().all()
            if len(bound_images) != 1:
                raise UploadSessionError("Upload session is not active for this project.")
            image = bound_images[0]
            expected_object_key = source_image_key(project_id, image.filename)
            if upload.filename != image.filename or upload.object_key != expected_object_key:
                raise UploadSessionError(
                    "Upload filename or object key does not match the initialized session."
                )

            if is_local:
                try:
                    uuid_mod.UUID(upload.upload_id)
                except ValueError as exc:
                    raise UploadSessionError("Invalid local upload ID.") from exc
                staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload.upload_id
                session = load_local_upload_session(staging_dir)
                if (
                    session.project_id != str(project_id)
                    or session.image_id != str(image.id)
                    or session.object_key != expected_object_key
                ):
                    raise UploadSessionError("Upload session metadata does not match the database.")
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
            else:
                # MinIO mode: abort S3 multipart upload
                s3_service.abort_multipart_upload(
                    object_key=expected_object_key,
                    upload_id=upload.upload_id
                )

            image.upload_status = "failed"
            image.has_error = True

            aborted.append(upload.filename)

        except Exception as e:
            errors.append({
                "filename": upload.filename,
                "error": str(e)
            })

    await db.commit()

    return {
        "aborted": aborted,
        "errors": errors
    }


# ============================================================================
# Local Storage Chunk Upload - receives file chunks for local storage mode
# ============================================================================

@router.put("/projects/{project_id}/local/chunk")
async def upload_local_chunk(
    project_id: UUID,
    upload_id: str,
    part: int,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Receive a file chunk for local storage mode.

    Used instead of S3 presigned URL uploads when STORAGE_BACKEND=local.
    The URL with query params is returned by init_multipart_upload.
    """
    # Check permission for the target project
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Validate upload_id is a valid UUID (prevents path traversal)
    try:
        uuid_mod.UUID(upload_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid upload_id format",
        )

    staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload_id
    if not staging_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )

    try:
        session = load_local_upload_session(staging_dir)
    except UploadSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    if session.project_id != str(project_id) or session.upload_id != upload_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload session does not belong to this project",
        )

    image_result = await db.execute(
        select(Image).where(
            Image.id == UUID(session.image_id),
            Image.project_id == project_id,
            Image.upload_id == upload_id,
            Image.upload_status == "uploading",
        )
    )
    if image_result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Active upload record not found",
        )

    try:
        required_size = expected_part_size(session.file_size, session.part_size, part)
    except UploadSessionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_size = int(content_length)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid Content-Length",
            ) from exc
        if declared_size != required_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chunk size must be exactly {required_size} bytes",
            )

    part_path = staging_dir / f"part_{part}"
    temporary_path = staging_dir / f".part_{part}.tmp"
    temporary_path.unlink(missing_ok=True)

    # Stream to a temporary file with a hard byte limit, then publish atomically.
    digest = hashlib.md5()
    written = 0
    try:
        with open(temporary_path, "wb") as f:
            async for chunk in request.stream():
                written += len(chunk)
                if written > required_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail="Chunk exceeds the initialized size",
                    )
                f.write(chunk)
                digest.update(chunk)

        if written != required_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Chunk size must be exactly {required_size} bytes",
            )
        temporary_path.replace(part_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return {"etag": digest.hexdigest(), "part_number": part}
