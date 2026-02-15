"""Upload API endpoints with tus webhook handling and S3 multipart upload."""
import json
import hashlib
import hmac
import uuid as uuid_mod
from uuid import UUID
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image, CameraModel
from app.schemas.project import ImageResponse, ImageUploadResponse
from app.auth.jwt import get_current_user, PermissionChecker, is_admin_role
from app.config import get_settings
from app.services.storage import get_storage
from app.services.quota import ensure_organization_quota


def _verify_tus_webhook_request(token: str, signature: str, body: bytes) -> None:
    """Verify tus hook caller.

    - If TUS_WEBHOOK_TOKEN is configured, caller must provide either:
      - X-Tus-Webhook-Token header (exact match)
      - token query param match
      - or X-Tus-Signature (HMAC-SHA256) in header
    - If token is not configured, behavior keeps backward compatibility.
    """
    if not settings.TUS_WEBHOOK_TOKEN:
        return

    token_ok = (
        token == settings.TUS_WEBHOOK_TOKEN
        or signature == hashlib.sha256(body + settings.TUS_WEBHOOK_TOKEN.encode()).hexdigest()
    )
    if token_ok:
        return

    # HMAC verification
    if signature:
        expected_signature = hmac.new(
            settings.TUS_WEBHOOK_TOKEN.encode(), body, hashlib.sha256
        ).hexdigest()
        if hmac.compare_digest(signature, expected_signature):
            return

    raise HTTPException(status_code=403, detail="Invalid TUS webhook auth")

router = APIRouter(prefix="/upload", tags=["Upload"])
settings = get_settings()


async def _get_scoped_project(
    project_id: UUID,
    current_user: User,
    db: AsyncSession,
):
    query = select(Project).where(Project.id == project_id)
    if not is_admin_role(current_user.role):
        query = query.where(Project.organization_id == current_user.organization_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()

# Lazy import for MinIO-only service
def _get_s3_multipart_service():
    from app.services.s3_multipart import get_s3_multipart_service
    return get_s3_multipart_service()


@router.post("/projects/{project_id}/images/init", response_model=ImageUploadResponse)
async def initiate_image_upload(
    project_id: UUID,
    filename: str,
    file_size: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Initiate a resumable image upload.
    Returns tus upload URL for client to use.
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

    # Check if image with same filename already exists (prevent duplicates)
    existing_result = await db.execute(
        select(Image).where(
            Image.project_id == project_id,
            Image.filename == filename,
        )
    )
    existing_image = existing_result.scalar_one_or_none()

    if existing_image:
        additional_bytes = max(file_size - (existing_image.file_size or 0), 0)
        # Reset status to uploading for retry/re-upload
        existing_image.upload_status = "uploading"
        existing_image.file_size = file_size
        await ensure_organization_quota(
            db,
            current_user.organization_id,
            additional_storage_bytes=additional_bytes,
        )
        await db.commit()
        await db.refresh(existing_image)
        image = existing_image
    else:
        await ensure_organization_quota(
            db,
            current_user.organization_id,
            additional_storage_bytes=file_size,
        )
        # Create new image record
        image = Image(
            project_id=project_id,
            filename=filename,
            file_size=file_size,
            upload_status="uploading",
        )
        db.add(image)
        await db.commit()
        await db.refresh(image)
    
    # The upload_id will be set by tus server via webhook
    # For now, we generate a placeholder that maps to the image
    upload_id = f"img_{image.id}"
    
    return ImageUploadResponse(
        image_id=image.id,
        upload_url=f"{settings.TUS_ENDPOINT}",
        upload_id=upload_id,
    )


@router.post("/hooks")
async def tus_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Handle tus server webhooks for upload lifecycle events.
    
    Events:
    - pre-create: Validate upload before creation
    - post-finish: Process completed upload
    - post-terminate: Handle cancelled upload
    """
    body = await request.body()

    _verify_tus_webhook_request(
        request.headers.get("X-Tus-Webhook-Token")
        or request.query_params.get("token")
        or request.headers.get("Authorization")
        or "",
        request.headers.get("X-Tus-Signature") or "",
        body,
    )

    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_type = data.get("Type")
    # tusd sends metadata under Event.Upload (not direct Upload)
    event_data = data.get("Event", {})
    upload_info = event_data.get("Upload", {})
    metadata = upload_info.get("MetaData", {})
    
    if event_type == "pre-create":
        # Check if this is a partial upload (from parallel uploads)
        is_partial = upload_info.get("IsPartial", False)
        
        # Partial uploads don't have metadata - allow them
        if is_partial:
            return {}  # Accept partial upload
        
        # Validate the upload (check user auth, file type, etc.)
        project_id = metadata.get("projectId")
        filename = metadata.get("filename", "")
        
        if not project_id:
            return {"RejectUpload": True, "Message": "Missing projectId"}
        
        # Check file extension
        allowed_extensions = [".jpg", ".jpeg", ".png", ".tif", ".tiff", ".raw"]
        ext = "." + filename.split(".")[-1].lower() if "." in filename else ""
        if ext not in allowed_extensions:
            return {"RejectUpload": True, "Message": f"Invalid file type: {ext}"}
        
        return {}  # Accept upload
    
    elif event_type == "post-finish":
        # Upload completed successfully
        upload_id = upload_info.get("ID")
        storage_path = upload_info.get("Storage", {}).get("Key")
        
        # Find and update the image record
        project_id = metadata.get("projectId")
        filename = metadata.get("filename")
        
        if project_id and filename:
            result = await db.execute(
                select(Image).where(
                    Image.project_id == project_id,
                    Image.filename == filename,
                    Image.upload_status == "uploading",
                )
            )
            image = result.scalar_one_or_none()
            
            if image:
                image.upload_id = upload_id
                image.original_path = storage_path
                image.upload_status = "completed"
                await db.commit()
                
                # Trigger thumbnail generation in background
                try:
                    from app.workers.tasks import generate_thumbnail
                    generate_thumbnail.delay(str(image.id))
                except Exception as e:
                    print(f"Failed to trigger thumbnail task: {e}")
        
        return {}
    
    elif event_type == "post-terminate":
        # Upload was cancelled
        upload_id = upload_info.get("ID")
        
        # Mark image as failed
        result = await db.execute(
            select(Image).where(Image.upload_id == upload_id)
        )
        image = result.scalar_one_or_none()
        
        if image:
            image.upload_status = "failed"
            image.has_error = True
            await db.commit()
        
        return {}
    
    return {}


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
    from app.models.project import ExteriorOrientation, CameraModel

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

    storage = get_storage()
    response = []

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
            "thumbnail_url": storage.get_presigned_url(img.thumbnail_path) if img.thumbnail_path else None,
            "captured_at": img.captured_at,
            "resolution": img.resolution,
            "file_size": img.file_size,
            "has_error": img.has_error,
            "upload_status": img.upload_status,
            "created_at": img.created_at,
            # Image dimensions
            "image_width": img.image_width,
            "image_height": img.image_height,
            # Camera model
            "camera_model": img.camera_model,
            "exterior_orientation": img.exterior_orientation,
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


@router.post("/images/{image_id}/regenerate-thumbnail")
async def regenerate_image_thumbnail(
    image_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Regenerate thumbnail for a specific image."""
    # Find the image
    result = await db.execute(
        select(Image).where(Image.id == image_id)
    )
    image = result.scalar_one_or_none()

    if not image:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Image not found",
        )

    scoped_project = await _get_scoped_project(image.project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(image.project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    try:
        from app.workers.tasks import generate_thumbnail
        task = generate_thumbnail.delay(str(image_id), force=True)
        return {
            "status": "triggered",
            "task_id": task.id,
            "message": f"Thumbnail regeneration started for image {image_id}",
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to trigger thumbnail regeneration: {str(e)}",
        )


# ============================================================================
# S3 Multipart Upload API - High-performance direct upload to MinIO
# ============================================================================

class FileInfo(BaseModel):
    """File information for multipart upload initialization."""
    filename: str
    size: int
    content_type: Optional[str] = "application/octet-stream"


class MultipartInitRequest(BaseModel):
    """Request body for multipart upload initialization."""
    files: List[FileInfo]
    part_size: Optional[int] = 10 * 1024 * 1024  # 10MB default
    camera_model_name: Optional[str] = None  # Link images to camera model


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
    part_number: int
    etag: str


class CompletedUpload(BaseModel):
    """Completed upload information."""
    filename: str
    upload_id: str
    object_key: str
    parts: List[CompletedPart]


class MultipartCompleteRequest(BaseModel):
    """Request body for completing multipart uploads."""
    uploads: List[CompletedUpload]


class CompletedFileInfo(BaseModel):
    """Information about a completed file."""
    filename: str
    image_id: UUID
    status: str


class MultipartCompleteResponse(BaseModel):
    """Response for multipart upload completion."""
    completed: List[CompletedFileInfo]
    failed: List[dict]


class AbortUpload(BaseModel):
    """Upload to abort."""
    filename: str
    upload_id: str
    object_key: str


class MultipartAbortRequest(BaseModel):
    """Request body for aborting multipart uploads."""
    uploads: List[AbortUpload]


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

    # Sanitize filenames and calculate incremental storage demand
    safe_filenames = []
    import os
    for file_info in request.files:
        safe_filename = os.path.basename(file_info.filename)
        if not safe_filename or safe_filename.startswith(".") or ".." in file_info.filename:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid filename: {file_info.filename}",
            )
        safe_filenames.append(safe_filename)
        file_info.filename = safe_filename

    existing_result = await db.execute(
        select(Image.filename, Image.file_size)
        .where(
            Image.project_id == project_id,
            Image.filename.in_(safe_filenames),
        )
    )
    existing_sizes = {row.filename: row.file_size or 0 for row in existing_result.all()}

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
        select(Image).where(
            Image.project_id == project_id,
            Image.filename.in_(safe_filenames),
        )
    )
    existing_images = {img.filename: img for img in existing_image_rows.scalars().all()}

    # Look up camera model if provided
    camera_model_id = None
    if request.camera_model_name:
        cam_result = await db.execute(
            select(CameraModel).where(CameraModel.name == request.camera_model_name)
        )
        camera_model = cam_result.scalar_one_or_none()
        if camera_model:
            camera_model_id = camera_model.id

    is_local = settings.STORAGE_BACKEND == "local"

    # Only initialize S3 service when in MinIO mode
    s3_service = None if is_local else _get_s3_multipart_service()

    for file_info in request.files:
        # Create or update image record
        existing_image = existing_images.get(file_info.filename)

        if existing_image:
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
        object_key = f"images/{project_id}/{file_info.filename}"

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

            # Create staging directory
            staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload_id
            staging_dir.mkdir(parents=True, exist_ok=True)
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
    completed = []
    failed = []

    for upload in request.uploads:
        try:
            # Validate upload_id format
            try:
                uuid_mod.UUID(upload.upload_id)
            except ValueError:
                failed.append({"filename": upload.filename, "error": "Invalid upload_id"})
                continue

            # Validate object_key belongs to this project (prevent cross-project writes)
            expected_prefix = f"images/{project_id}/"
            if not upload.object_key.startswith(expected_prefix) or ".." in upload.object_key:
                failed.append({"filename": upload.filename, "error": "Invalid object_key for this project"})
                continue

            if is_local:
                # Local mode: merge chunks and move to storage
                import shutil
                staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload.upload_id

                # Determine number of parts from the sorted staging files
                part_files = sorted(staging_dir.glob("part_*"), key=lambda p: int(p.name.split("_")[1]))
                if not part_files:
                    failed.append({"filename": upload.filename, "error": "No uploaded parts found"})
                    continue

                # Merge chunks into final path in storage
                storage = get_storage()
                final_path = Path(storage.get_local_path(upload.object_key))
                final_path.parent.mkdir(parents=True, exist_ok=True)

                with open(final_path, "wb") as out_f:
                    for part_file in part_files:
                        with open(part_file, "rb") as in_f:
                            shutil.copyfileobj(in_f, out_f)

                # Clean up staging directory
                shutil.rmtree(staging_dir, ignore_errors=True)
            else:
                # MinIO mode: complete S3 multipart upload
                s3_service.complete_multipart_upload(
                    object_key=upload.object_key,
                    upload_id=upload.upload_id,
                    parts=[{"part_number": p.part_number, "etag": p.etag} for p in upload.parts]
                )

            # Update image record
            result = await db.execute(
                select(Image).where(
                    Image.project_id == project_id,
                    Image.filename == upload.filename,
                    Image.upload_status == "uploading",
                )
            )
            image = result.scalar_one_or_none()

            if image:
                image.upload_id = upload.upload_id
                image.original_path = upload.object_key
                image.upload_status = "completed"

                completed.append(CompletedFileInfo(
                    filename=upload.filename,
                    image_id=image.id,
                    status="completed"
                ))

                # Trigger thumbnail generation
                try:
                    from app.workers.tasks import generate_thumbnail
                    generate_thumbnail.delay(str(image.id))
                except Exception as e:
                    print(f"Failed to trigger thumbnail task: {e}")
            else:
                failed.append({
                    "filename": upload.filename,
                    "error": "Image record not found"
                })

        except Exception as e:
            failed.append({
                "filename": upload.filename,
                "error": str(e)
            })

    await db.commit()

    # --- Scheduled processing trigger hook ---
    # Check if this project has a scheduled processing job and all images are now uploaded
    if completed:
        try:
            from app.models.project import ProcessingJob, Image
            from sqlalchemy import func

            # Check for a scheduled job
            sched_result = await db.execute(
                select(ProcessingJob).where(
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.status == "scheduled",
                )
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

                if pending_or_uploading == 0 and completed_images > 0:
                    # All images uploaded — update DB state first (atomic)
                    scheduled_job.status = "queued"
                    scoped_project.status = "queued"
                    scoped_project.progress = 0

                    options_dict = {
                        "engine": scheduled_job.engine,
                        "gsd": scheduled_job.gsd,
                        "output_crs": scheduled_job.output_crs,
                        "output_format": scheduled_job.output_format,
                        "process_mode": scheduled_job.process_mode or "Normal",
                    }
                    queue_name = scheduled_job.engine or "metashape"

                    # Commit DB changes BEFORE submitting to Celery
                    await db.commit()

                    # Now submit Celery task — DB is already consistent
                    try:
                        from app.workers.tasks import process_orthophoto
                        task = process_orthophoto.apply_async(
                            args=[str(scheduled_job.id), str(project_id), options_dict],
                            queue=queue_name,
                        )
                        # Update celery_task_id (non-critical)
                        scheduled_job.celery_task_id = task.id
                        await db.commit()
                        print(f"[Scheduled Processing] Auto-triggered for project {project_id}, job {scheduled_job.id}")
                    except Exception as celery_err:
                        # Celery submission failed — revert DB state
                        print(f"[Scheduled Processing] Celery submission failed: {celery_err}")
                        scheduled_job.status = "scheduled"
                        scoped_project.status = "scheduled"
                        await db.commit()
        except Exception as e:
            # Don't fail the upload completion if the trigger fails
            print(f"[Scheduled Processing] Trigger check failed: {e}")

    return MultipartCompleteResponse(completed=completed, failed=failed)


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
            # Validate upload_id format
            try:
                uuid_mod.UUID(upload.upload_id)
            except ValueError:
                errors.append({"filename": upload.filename, "error": "Invalid upload_id"})
                continue

            # Validate object_key belongs to this project
            expected_prefix = f"images/{project_id}/"
            if not upload.object_key.startswith(expected_prefix) or ".." in upload.object_key:
                errors.append({"filename": upload.filename, "error": "Invalid object_key for this project"})
                continue

            if is_local:
                # Local mode: clean up staging directory
                import shutil
                staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload.upload_id
                if staging_dir.exists():
                    shutil.rmtree(staging_dir, ignore_errors=True)
            else:
                # MinIO mode: abort S3 multipart upload
                s3_service.abort_multipart_upload(
                    object_key=upload.object_key,
                    upload_id=upload.upload_id
                )

            # Update image record
            result = await db.execute(
                select(Image).where(
                    Image.project_id == project_id,
                    Image.filename == upload.filename,
                )
            )
            image = result.scalar_one_or_none()

            if image:
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

    if part < 1 or part > 10000:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid part number",
        )

    staging_dir = Path(settings.LOCAL_STORAGE_PATH) / ".uploads" / upload_id
    if not staging_dir.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload session not found",
        )

    part_path = staging_dir / f"part_{part}"

    # Stream request body directly to disk (memory-efficient)
    with open(part_path, "wb") as f:
        async for chunk in request.stream():
            f.write(chunk)

    # Return a fake ETag for compatibility with the frontend flow
    import hashlib
    file_size = part_path.stat().st_size
    etag = hashlib.md5(f"{upload_id}:{part}:{file_size}".encode()).hexdigest()

    return {"etag": etag, "part_number": part}
