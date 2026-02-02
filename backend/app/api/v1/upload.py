"""Upload API endpoints with tus webhook handling and S3 multipart upload."""
import json
from uuid import UUID
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Request, status, Body
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image
from app.schemas.project import ImageResponse, ImageUploadResponse
from app.auth.jwt import get_current_user, PermissionChecker
from app.config import get_settings
from app.services.storage import get_storage
from app.services.s3_multipart import get_s3_multipart_service

router = APIRouter(prefix="/upload", tags=["Upload"])
settings = get_settings()


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
    
    # Check project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
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
        # Reset status to uploading for retry/re-upload
        existing_image.upload_status = "uploading"
        existing_image.file_size = file_size
        await db.commit()
        await db.refresh(existing_image)
        image = existing_image
    else:
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
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON")
    
    event_type = data.get("Type")
    # tusd sends metadata under Event.Upload (not direct Upload)
    event_data = data.get("Event", {})
    upload_info = event_data.get("Upload", {})
    metadata = upload_info.get("MetaData", {})
    
    print(f"TUS Webhook RAW: {data}")  # Full payload
    print(f"TUS Webhook: {event_type} - {metadata}") # DEBUG LOG
    
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

    from sqlalchemy.orm import joinedload
    from app.models.project import ExteriorOrientation

    result = await db.execute(
        select(Image)
        .options(joinedload(Image.exterior_orientation))
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

    # Check project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    s3_service = get_s3_multipart_service()
    uploads = []

    for file_info in request.files:
        # Create or update image record
        existing_result = await db.execute(
            select(Image).where(
                Image.project_id == project_id,
                Image.filename == file_info.filename,
            )
        )
        existing_image = existing_result.scalar_one_or_none()

        if existing_image:
            existing_image.upload_status = "uploading"
            existing_image.file_size = file_info.size
            await db.flush()
            image = existing_image
        else:
            image = Image(
                project_id=project_id,
                filename=file_info.filename,
                file_size=file_info.size,
                upload_status="uploading",
            )
            db.add(image)
            await db.flush()

        # Generate object key
        object_key = f"images/{project_id}/{file_info.filename}"

        # Create multipart upload
        upload_id = s3_service.create_multipart_upload(
            object_key=object_key,
            content_type=file_info.content_type
        )

        # Generate presigned URLs for parts
        parts = s3_service.generate_part_presigned_urls(
            object_key=object_key,
            upload_id=upload_id,
            file_size=file_info.size,
            part_size=request.part_size
        )

        uploads.append(UploadInfo(
            filename=file_info.filename,
            image_id=image.id,
            upload_id=upload_id,
            object_key=object_key,
            parts=[PartInfo(**p) for p in parts]
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

    s3_service = get_s3_multipart_service()
    completed = []
    failed = []

    for upload in request.uploads:
        try:
            # Complete the S3 multipart upload
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

    s3_service = get_s3_multipart_service()
    aborted = []
    errors = []

    for upload in request.uploads:
        try:
            # Abort the S3 multipart upload
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
