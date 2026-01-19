"""Download API endpoints with resumable download support."""
import os
import re
import hashlib
from urllib.parse import quote
from uuid import UUID
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiofiles

from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob
from app.auth.jwt import get_current_user, PermissionChecker
from app.services.storage import StorageService

router = APIRouter(prefix="/download", tags=["Download"])


async def calculate_file_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file."""
    hash_sha256 = hashlib.sha256()
    async with aiofiles.open(file_path, 'rb') as f:
        while chunk := await f.read(1024 * 1024):  # 1MB chunks
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


@router.get("/projects/{project_id}/ortho")
async def download_orthophoto(
    project_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download the orthophoto result with resumable download support.
    
    Supports HTTP Range requests for partial content / resume.
    Returns SHA256 checksum in X-File-Checksum header for client verification.
    """
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    # Get the latest completed processing job
    result = await db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status == "completed",
        )
        .order_by(ProcessingJob.completed_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if not job or not job.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthophoto found for this project",
        )
    
    # For MinIO files, we'll use presigned URLs or stream from storage
    # For now, assume local file path
    file_path = job.result_path
    
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result file not found",
        )
    
    file_size = os.path.getsize(file_path)
    
    # Get or calculate checksum
    if job.result_checksum:
        file_checksum = job.result_checksum
    else:
        file_checksum = await calculate_file_checksum(file_path)
        # Cache the checksum
        job.result_checksum = file_checksum
        await db.commit()
    
    etag = f'"{file_checksum}"'
    
    # Check ETag for caching
    if request.headers.get("If-None-Match") == etag:
        return StreamingResponse(
            iter([]),
            status_code=status.HTTP_304_NOT_MODIFIED,
        )
    
    # Parse Range header
    range_header = request.headers.get("Range")
    
    # Get project title for filename
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one()
    # Use URL encoding for non-ASCII filenames (RFC 5987)
    base_filename = f"{project.title}_ortho.tif".replace(" ", "_")
    # Create ASCII-safe fallback and UTF-8 encoded version
    ascii_filename = f"{project_id}_ortho.tif"  # Fallback
    encoded_filename = quote(base_filename, safe='')
    
    if range_header:
        # Partial content (resumable download)
        range_match = re.match(r'bytes=(\d+)-(\d*)', range_header)
        if not range_match:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail="Invalid Range header",
            )
        
        start = int(range_match.group(1))
        end = int(range_match.group(2)) if range_match.group(2) else file_size - 1
        
        if start >= file_size or end >= file_size or start > end:
            raise HTTPException(
                status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
                detail=f"Range out of bounds. File size: {file_size}",
            )
        
        content_length = end - start + 1
        
        async def iter_file_range():
            """Stream file content for the specified range."""
            async with aiofiles.open(file_path, 'rb') as f:
                await f.seek(start)
                remaining = content_length
                while remaining > 0:
                    chunk_size = min(8 * 1024 * 1024, remaining)  # 8MB chunks
                    chunk = await f.read(chunk_size)
                    if not chunk:
                        break
                    remaining -= len(chunk)
                    yield chunk
        
        return StreamingResponse(
            iter_file_range(),
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            headers={
                "Content-Range": f"bytes {start}-{end}/{file_size}",
                "Content-Length": str(content_length),
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "X-File-Checksum": file_checksum,
                "X-File-Size": str(file_size),
                "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}",
            },
            media_type="image/tiff",
        )
    
    else:
        # Full content download
        async def iter_file():
            """Stream entire file content."""
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(8 * 1024 * 1024):  # 8MB chunks
                    yield chunk
        
        return StreamingResponse(
            iter_file(),
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
                "ETag": etag,
                "X-File-Checksum": file_checksum,
                "X-File-Size": str(file_size),
                "Content-Disposition": f"attachment; filename=\"{ascii_filename}\"; filename*=UTF-8''{encoded_filename}",
            },
            media_type="image/tiff",
        )


@router.head("/projects/{project_id}/ortho")
async def get_download_info(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get file info (size, checksum) without downloading.
    Used by clients to check file size before resumable download.
    """
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    # Get the latest completed processing job
    result = await db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status == "completed",
        )
        .order_by(ProcessingJob.completed_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if not job or not job.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthophoto found",
        )
    
    file_path = job.result_path
    if not os.path.exists(file_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result file not found",
        )
    
    file_size = os.path.getsize(file_path)
    checksum = job.result_checksum or await calculate_file_checksum(file_path)
    
    return StreamingResponse(
        iter([]),
        headers={
            "Content-Length": str(file_size),
            "Accept-Ranges": "bytes",
            "X-File-Checksum": checksum,
            "X-File-Size": str(file_size),
        },
    )


@router.get("/projects/{project_id}/cog-url")
async def get_cog_url(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Get a presigned URL for COG streaming.
    
    This URL can be used by geotiff.js to stream the orthophoto
    directly from storage with Range Request support.
    
    Returns:
        url: Presigned URL for the COG file
        bounds: Geographic bounds [west, south, east, north]
        file_size: Size of the file in bytes
    """
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    # Get the latest completed processing job
    result = await db.execute(
        select(ProcessingJob)
        .where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status == "completed",
        )
        .order_by(ProcessingJob.completed_at.desc())
    )
    job = result.scalar_one_or_none()
    
    if not job or not job.result_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthophoto found for this project",
        )
    
    file_path = job.result_path
    
    # Check if file exists locally
    if os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
        # For local files, return the streaming endpoint URL
        # The /ortho endpoint already supports Range requests
        return {
            "url": f"/api/v1/download/projects/{project_id}/ortho",
            "local": True,
            "file_size": file_size,
            "project_id": str(project_id),
        }
    
    # For MinIO files, generate presigned URL
    storage = StorageService()
    object_name = file_path  # Assuming result_path is the MinIO object name
    
    if not storage.object_exists(object_name):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Result file not found in storage",
        )
    
    file_size = storage.get_object_size(object_name)
    
    # Generate presigned URL valid for 1 hour
    presigned_url = storage.get_presigned_url(object_name, expires=3600)
    
    return {
        "url": presigned_url,
        "local": False,
        "file_size": file_size,
        "project_id": str(project_id),
    }


from pydantic import BaseModel
from typing import List
import zipfile
import io
import tempfile


class BatchExportRequest(BaseModel):
    """Request model for batch export."""
    project_ids: List[UUID]
    format: str = "GeoTiff"
    crs: str = "EPSG:5186"


@router.post("/batch")
async def batch_download(
    request: BatchExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download multiple project orthoimages as a ZIP archive.
    
    This endpoint creates a ZIP file containing all completed orthoimages
    from the requested projects.
    """
    if not request.project_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No project IDs provided",
        )
    
    if len(request.project_ids) > 20:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Maximum 20 projects allowed per batch export",
        )
    
    # Get all eligible projects
    projects_with_files = []
    
    for project_id in request.project_ids:
        # Check permission
        permission_checker = PermissionChecker("view")
        if not await permission_checker.check(str(project_id), current_user, db):
            continue  # Skip projects without permission
        
        # Get the latest completed processing job
        result = await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.project_id == project_id,
                ProcessingJob.status == "completed",
            )
            .order_by(ProcessingJob.completed_at.desc())
        )
        job = result.scalar_one_or_none()
        
        if not job or not job.result_path:
            continue  # Skip projects without completed orthoimages
        
        file_path = job.result_path
        if not os.path.exists(file_path):
            continue  # Skip if file doesn't exist
        
        # Get project info for filename
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        if project:
            projects_with_files.append({
                "project": project,
                "file_path": file_path,
            })
    
    if not projects_with_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthoimages found for the selected projects",
        )
    
    # Create ZIP file in memory (for small batches) or temp file (for large)
    # Using tempfile for reliability
    temp_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix='.zip').name
    
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for item in projects_with_files:
                project = item["project"]
                file_path = item["file_path"]
                
                # Create safe filename
                safe_title = project.title.replace(" ", "_").replace("/", "_")
                arcname = f"{safe_title}_ortho.tif"
                
                # Add file to zip
                zipf.write(file_path, arcname)
        
        # Stream the ZIP file
        zip_size = os.path.getsize(temp_zip_path)
        
        async def iter_zip_file():
            """Stream the ZIP file content."""
            try:
                async with aiofiles.open(temp_zip_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):  # 8MB chunks
                        yield chunk
            finally:
                # Clean up temp file after streaming
                try:
                    os.unlink(temp_zip_path)
                except:
                    pass
        
        # Generate filename with timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_filename = f"batch_export_{timestamp}.zip"
        
        return StreamingResponse(
            iter_zip_file(),
            headers={
                "Content-Length": str(zip_size),
                "Content-Disposition": f'attachment; filename="{zip_filename}"',
            },
            media_type="application/zip",
        )
        
    except Exception as e:
        # Clean up on error
        try:
            os.unlink(temp_zip_path)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create ZIP archive: {str(e)}",
        )
