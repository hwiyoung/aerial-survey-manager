"""Upload API endpoints with tus webhook handling."""
import json
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image
from app.schemas.project import ImageResponse, ImageUploadResponse
from app.auth.jwt import get_current_user, PermissionChecker
from app.config import get_settings
from app.services.storage import get_storage

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
    for img in images:
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
    
    return response
