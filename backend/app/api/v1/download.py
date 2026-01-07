"""Download API endpoints with resumable download support."""
import os
import re
import hashlib
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
    filename = f"{project.title}_ortho.tif".replace(" ", "_")
    
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
                "Content-Disposition": f'attachment; filename="{filename}"',
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
                "Content-Disposition": f'attachment; filename="{filename}"',
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
