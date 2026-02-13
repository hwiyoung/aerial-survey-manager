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
from app.services.storage import get_storage

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
    
    # Check local file first, then fall back to MinIO
    file_path = job.result_path
    temp_file_path = None

    if file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    else:
        # Fallback: try Project.ortho_path in MinIO, then job.result_path as MinIO key
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        proj = project_result.scalar_one()

        storage = get_storage()
        minio_key = None

        if proj.ortho_path and storage.object_exists(proj.ortho_path):
            minio_key = proj.ortho_path
        elif file_path and storage.object_exists(file_path):
            minio_key = file_path

        if not minio_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result file not found (local or storage)",
            )

        # Download from MinIO to temp file
        import tempfile as tf
        temp_file = tf.NamedTemporaryFile(delete=False, suffix='.tif')
        temp_file.close()
        storage.download_file(minio_key, temp_file.name)
        file_path = temp_file.name
        temp_file_path = temp_file.name
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
            try:
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
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try: os.unlink(temp_file_path)
                    except: pass
        
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
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):  # 8MB chunks
                        yield chunk
            finally:
                if temp_file_path and os.path.exists(temp_file_path):
                    try: os.unlink(temp_file_path)
                    except: pass
        
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
    file_size = None

    if file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    else:
        # Fallback to MinIO
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        proj = project_result.scalar_one()
        storage = get_storage()
        minio_key = None
        if proj.ortho_path and storage.object_exists(proj.ortho_path):
            minio_key = proj.ortho_path
        elif file_path and storage.object_exists(file_path):
            minio_key = file_path
        if minio_key:
            file_size = storage.get_object_size(minio_key)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result file not found",
            )

    checksum = job.result_checksum or (await calculate_file_checksum(file_path) if os.path.exists(file_path) else None)
    
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
    
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one()

    storage = get_storage()

    # Try Project.ortho_path first, then fall back to ProcessingJob
    ortho_path = project.ortho_path
    if not ortho_path:
        result = await db.execute(
            select(ProcessingJob)
            .where(
                ProcessingJob.project_id == project_id,
                ProcessingJob.status == "completed",
            )
            .order_by(ProcessingJob.completed_at.desc())
        )
        job = result.scalar_one_or_none()
        if job and job.result_path:
            ortho_path = job.result_path

    if not ortho_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthophoto found for this project",
        )

    # Local storage mode: return file:// URL for TiTiler direct access
    local_path = storage.get_local_path(ortho_path)
    if local_path and os.path.exists(local_path):
        file_size = os.path.getsize(local_path)
        return {
            "url": f"file://{local_path}",
            "local": True,
            "file_size": file_size,
            "project_id": str(project_id),
        }

    # MinIO mode: check if object exists in storage
    if storage.object_exists(ortho_path):
        file_size = storage.get_object_size(ortho_path)
        s3_url = f"s3://{storage.bucket}/{ortho_path}"
        return {
            "url": s3_url,
            "local": False,
            "file_size": file_size,
            "project_id": str(project_id),
        }

    # Check if it's a local file path (legacy processing jobs)
    if os.path.exists(ortho_path):
        file_size = os.path.getsize(ortho_path)
        return {
            "url": f"file://{ortho_path}",
            "local": True,
            "file_size": file_size,
            "project_id": str(project_id),
        }

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Result file not found in storage",
    )


from pydantic import BaseModel
from typing import List, Dict
import zipfile
import io
import tempfile
import uuid
import time
from datetime import datetime


class BatchExportRequest(BaseModel):
    """Request model for batch export."""
    project_ids: List[UUID]
    format: str = "GeoTiff"
    crs: str = "EPSG:5186"
    gsd: float | None = None  # Planned GSD in cm/pixel (None = use original)
    custom_filename: str | None = None  # Optional custom filename for ZIP


def get_source_gsd_and_crs(file_path: str) -> tuple[float | None, str]:
    """Extract GSD (m) and CRS from a GeoTIFF file using gdalinfo."""
    import subprocess
    import json
    import re

    try:
        result = subprocess.run(["gdalinfo", "-json", file_path], capture_output=True, text=True)
        if result.returncode != 0:
            return None, "Unknown"

        info = json.loads(result.stdout)

        # Get CRS
        source_wkt = info.get('coordinateSystem', {}).get('wkt', '') or info.get('stac', {}).get('proj:wkt2', '')
        epsg_match = re.search(r'ID\["EPSG",(\d+)\]', source_wkt)
        source_crs = f"EPSG:{epsg_match.group(1)}" if epsg_match else "Unknown"

        # Get GSD (pixel size in meters)
        geo_transform = info.get('geoTransform', [])
        if len(geo_transform) >= 2:
            # geoTransform[1] is pixel width in CRS units (meters for projected CRS)
            pixel_size = abs(geo_transform[1])
            return pixel_size, source_crs

        return None, source_crs
    except Exception as e:
        print(f"DEBUG: Failed to get GSD/CRS: {e}")
        return None, "Unknown"


# 임시 다운로드 저장소 (download_id -> file_info)
# 실제 운영에서는 Redis 등을 사용하는 것이 좋음
_pending_downloads: Dict[str, dict] = {}


def cleanup_old_downloads():
    """5분 이상 지난 다운로드 정리"""
    now = time.time()
    expired = [k for k, v in _pending_downloads.items() if now - v.get("created_at", 0) > 300]
    for k in expired:
        info = _pending_downloads.pop(k, None)
        if info and info.get("file_path") and os.path.exists(info["file_path"]):
            try:
                os.unlink(info["file_path"])
            except:
                pass


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
        
        # First check Project.ortho_path (preferred)
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()
        
        if not project:
            continue
        
        ortho_path = project.ortho_path
        
        # Fallback to ProcessingJob.result_path if ortho_path is not set
        if not ortho_path:
            result = await db.execute(
                select(ProcessingJob)
                .where(
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.status == "completed",
                )
                .order_by(ProcessingJob.completed_at.desc())
            )
            job = result.scalar_one_or_none()
            if job and job.result_path:
                ortho_path = job.result_path
        
        if not ortho_path:
            continue  # Skip projects without orthoimage
        
        # Check if it's a MinIO path or local path
        storage = get_storage()
        source_path = None
        if storage.object_exists(ortho_path):
            # Download from MinIO to temp file
            import tempfile as tf
            temp_file = tf.NamedTemporaryFile(delete=False, suffix='.tif')
            temp_file.close()  # Close before writing
            storage.download_file(ortho_path, temp_file.name)
            
            # Verify file size after download (prevents corruption)
            expected_size = storage.get_object_size(ortho_path)
            actual_size = os.path.getsize(temp_file.name)
            if actual_size != expected_size:
                os.unlink(temp_file.name)
                continue  # Skip corrupted download
            
            source_path = temp_file.name
        elif os.path.exists(ortho_path):
            source_path = ortho_path
        else:
            continue  # Skip if file doesn't exist anywhere
        
        # --- Handle Re-projection if requested (Fixing the 3857 issue) ---
        target_crs = request.crs
        final_file_path = source_path

        try:
            import subprocess
            import json
            import re
            import sys

            # Get source GSD and CRS from the file
            source_gsd_m, source_epsg = get_source_gsd_and_crs(source_path)
            source_gsd_cm = source_gsd_m * 100 if source_gsd_m else None

            print(f"DEBUG: Processing export for project {project.id}", flush=True)
            print(f"DEBUG: Source GSD: {source_gsd_cm:.2f}cm, Source CRS: {source_epsg}", flush=True)

            # Calculate target resolution
            target_res = float(request.gsd) / 100.0 if request.gsd else None
            target_gsd_cm = request.gsd

            # Determine if warp is needed:
            # 1. CRS must be different, OR
            # 2. GSD must be significantly different (> 0.1 cm tolerance)
            crs_changed = (target_crs != source_epsg)
            gsd_changed = False

            if target_gsd_cm is not None and source_gsd_cm is not None:
                gsd_diff = abs(target_gsd_cm - source_gsd_cm)
                gsd_changed = gsd_diff > 0.1  # 0.1cm tolerance
                print(f"DEBUG: Target GSD: {target_gsd_cm:.2f}cm, Diff: {gsd_diff:.2f}cm, Changed: {gsd_changed}", flush=True)

            needs_warp = crs_changed or gsd_changed

            if not needs_warp:
                print(f"DEBUG: No changes needed - using existing COG directly", flush=True)
            
            if needs_warp:
                print(f"DEBUG: Warping starting: {source_path} ({source_epsg}) -> {target_crs} (GSD: {request.gsd}cm)", flush=True)
                warped_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'_{target_crs.replace(":", "_")}.tif')
                warped_file.close()
                
                warp_cmd = [
                    "gdalwarp",
                    "-t_srs", target_crs,
                    "-r", "bilinear",
                    "-overwrite",
                    "-co", "COMPRESS=LZW",
                ]
                
                if target_res:
                    # If target is WGS84 (EPSG:4326), GSD in meters must be converted to degrees
                    # 1 degree is roughly 111,320m. This is an approximation.
                    if target_crs == "EPSG:4326":
                        deg_res = target_res / 111320.0
                        print(f"DEBUG: Converting GSD {target_res}m to {deg_res} degrees for EPSG:4326", flush=True)
                        warp_cmd.extend(["-tr", f"{deg_res:.12f}", f"{deg_res:.12f}"])
                    else:
                        warp_cmd.extend(["-tr", str(target_res), str(target_res)])
                    
                warp_cmd.extend([source_path, warped_file.name])
                
                print(f"DEBUG: Executing command: {' '.join(warp_cmd)}", flush=True)
                result = subprocess.run(warp_cmd, capture_output=True, text=True)
                
                if result.returncode == 0:
                    final_file_path = warped_file.name
                    print(f"DEBUG: Successfully warped to {warped_file.name}", flush=True)
                    # If source was a temp file, delete it
                    if source_path.startswith(tempfile.gettempdir()):
                        try: os.unlink(source_path)
                        except: pass
                else:
                    print(f"ERROR: gdalwarp failed: {result.stderr}", flush=True)
            else:
                print(f"DEBUG: Skipping warp (Source EPSG '{source_epsg}' == Target '{target_crs}' and no GSD change)", flush=True)

        except Exception as warp_err:
            print(f"WARNING: Re-projection exception: {warp_err}", flush=True)
            import traceback
            traceback.print_exc()
            # Fallback to original file
        
        projects_with_files.append({
            "project": project,
            "file_path": final_file_path,
        })

    
    if not projects_with_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthoimages found for the selected projects",
        )
    
    # [DIAGNOSTIC] Log the number of projects found
    print(f"DEBUG: Batch download for project_ids={request.project_ids} found {len(projects_with_files)} files")
    
    # If only one project, stream the TIF directly (No ZIP)
    if len(projects_with_files) == 1:
        print(f"DEBUG: Single project branch triggered for {projects_with_files[0]['project'].id}")
        item = projects_with_files[0]
        project = item["project"]
        file_path = item["file_path"]
        
        # Determine filename
        if request.custom_filename:
            target_filename = request.custom_filename
            if not target_filename.lower().endswith('.tif') and not target_filename.lower().endswith('.tiff'):
                target_filename += ".tif"
        else:
            safe_title = project.title.replace(" ", "_").replace("/", "_")
            target_filename = f"{safe_title}_ortho.tif"
            
        file_size = os.path.getsize(file_path)
        encoded_filename = quote(target_filename)
        
        async def iter_tif_file():
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):
                        yield chunk
            finally:
                # Clean up if it was a temp download from MinIO
                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except: pass

        return StreamingResponse(
            iter_tif_file(),
            headers={
                "Content-Length": str(file_size),
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
            media_type="image/tiff",
        )

    # Multi-project: Use ZIP
    temp_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix='.zip').name
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            for item in projects_with_files:
                project = item["project"]
                file_path = item["file_path"]
                safe_title = project.title.replace(" ", "_").replace("/", "_")
                arcname = f"{safe_title}_ortho.tif"
                zipf.write(file_path, arcname)
                
                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except: pass
        
        zip_size = os.path.getsize(temp_zip_path)
        
        async def iter_zip_file():
            try:
                async with aiofiles.open(temp_zip_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):
                        yield chunk
            finally:
                try: os.unlink(temp_zip_path)
                except: pass
        
        if request.custom_filename:
            zip_filename = request.custom_filename
            if not zip_filename.lower().endswith('.zip'):
                zip_filename += ".zip"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"batch_export_{timestamp}.zip"
        
        encoded_filename = quote(zip_filename)
        return StreamingResponse(
            iter_zip_file(),
            headers={
                "Content-Length": str(zip_size),
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
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


@router.post("/batch/prepare")
async def prepare_batch_download(
    request: BatchExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    파일을 준비하고 다운로드 ID를 반환합니다.
    실제 다운로드는 GET /batch/{download_id}로 수행합니다.
    이 방식은 브라우저 메모리 문제를 방지합니다.
    """
    # 오래된 다운로드 정리
    cleanup_old_downloads()

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
        permission_checker = PermissionChecker("view")
        if not await permission_checker.check(str(project_id), current_user, db):
            continue

        project_result = await db.execute(select(Project).where(Project.id == project_id))
        project = project_result.scalar_one_or_none()

        if not project:
            continue

        ortho_path = project.ortho_path

        if not ortho_path:
            result = await db.execute(
                select(ProcessingJob)
                .where(
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.status == "completed",
                )
                .order_by(ProcessingJob.completed_at.desc())
            )
            job = result.scalar_one_or_none()
            if job and job.result_path:
                ortho_path = job.result_path

        if not ortho_path:
            continue

        storage = get_storage()
        source_path = None
        if storage.object_exists(ortho_path):
            import tempfile as tf
            temp_file = tf.NamedTemporaryFile(delete=False, suffix='.tif')
            temp_file.close()
            storage.download_file(ortho_path, temp_file.name)

            expected_size = storage.get_object_size(ortho_path)
            actual_size = os.path.getsize(temp_file.name)
            if actual_size != expected_size:
                os.unlink(temp_file.name)
                continue

            source_path = temp_file.name
        elif os.path.exists(ortho_path):
            source_path = ortho_path
        else:
            continue

        # Re-projection
        target_crs = request.crs
        final_file_path = source_path

        try:
            import subprocess
            import json
            import re as regex_module

            # Get source GSD and CRS from the file
            source_gsd_m, source_epsg = get_source_gsd_and_crs(source_path)
            source_gsd_cm = source_gsd_m * 100 if source_gsd_m else None

            print(f"DEBUG: [prepare] Processing export for project {project.id}", flush=True)
            print(f"DEBUG: [prepare] Source GSD: {source_gsd_cm:.2f}cm, Source CRS: {source_epsg}" if source_gsd_cm else f"DEBUG: [prepare] Source CRS: {source_epsg}", flush=True)

            # Calculate target resolution
            target_res = float(request.gsd) / 100.0 if request.gsd else None
            target_gsd_cm = request.gsd

            # Determine if warp is needed
            crs_changed = (target_crs != source_epsg)
            gsd_changed = False

            if target_gsd_cm is not None and source_gsd_cm is not None:
                gsd_diff = abs(target_gsd_cm - source_gsd_cm)
                gsd_changed = gsd_diff > 0.1  # 0.1cm tolerance
                print(f"DEBUG: [prepare] Target GSD: {target_gsd_cm:.2f}cm, Diff: {gsd_diff:.2f}cm, Changed: {gsd_changed}", flush=True)

            needs_warp = crs_changed or gsd_changed

            if not needs_warp:
                print(f"DEBUG: [prepare] No changes needed - using existing COG directly", flush=True)

            if needs_warp:
                print(f"DEBUG: [prepare] Warping: {source_epsg} -> {target_crs} (GSD: {request.gsd}cm)", flush=True)
                warped_file = tempfile.NamedTemporaryFile(delete=False, suffix=f'_{target_crs.replace(":", "_")}.tif')
                warped_file.close()

                warp_cmd = [
                    "gdalwarp",
                    "-t_srs", target_crs,
                    "-r", "bilinear",
                    "-overwrite",
                    "-co", "COMPRESS=LZW",
                ]

                if target_res:
                    if target_crs == "EPSG:4326":
                        deg_res = target_res / 111320.0
                        warp_cmd.extend(["-tr", f"{deg_res:.12f}", f"{deg_res:.12f}"])
                    else:
                        warp_cmd.extend(["-tr", str(target_res), str(target_res)])

                warp_cmd.extend([source_path, warped_file.name])

                print(f"DEBUG: [prepare] Executing: {' '.join(warp_cmd)}", flush=True)
                result = subprocess.run(warp_cmd, capture_output=True, text=True)

                if result.returncode == 0:
                    final_file_path = warped_file.name
                    print(f"DEBUG: [prepare] Successfully warped", flush=True)
                    if source_path.startswith(tempfile.gettempdir()):
                        try: os.unlink(source_path)
                        except: pass
                else:
                    print(f"ERROR: [prepare] gdalwarp failed: {result.stderr}", flush=True)

        except Exception as warp_err:
            print(f"WARNING: [prepare] Re-projection exception: {warp_err}", flush=True)
            import traceback
            traceback.print_exc()

        projects_with_files.append({
            "project": project,
            "file_path": final_file_path,
        })

    if not projects_with_files:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No completed orthoimages found for the selected projects",
        )

    # 다운로드 ID 생성
    download_id = str(uuid.uuid4())

    # 단일 프로젝트: TIF 그대로
    if len(projects_with_files) == 1:
        item = projects_with_files[0]
        project = item["project"]
        file_path = item["file_path"]

        if request.custom_filename:
            target_filename = request.custom_filename
            if not target_filename.lower().endswith('.tif') and not target_filename.lower().endswith('.tiff'):
                target_filename += ".tif"
        else:
            safe_title = project.title.replace(" ", "_").replace("/", "_")
            target_filename = f"{safe_title}_ortho.tif"

        file_size = os.path.getsize(file_path)

        _pending_downloads[download_id] = {
            "file_path": file_path,
            "filename": target_filename,
            "media_type": "image/tiff",
            "file_size": file_size,
            "created_at": time.time(),
        }

        return {
            "download_id": download_id,
            "filename": target_filename,
            "file_size": file_size,
        }

    # 다중 프로젝트: ZIP 생성
    temp_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix='.zip').name
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            for item in projects_with_files:
                project = item["project"]
                file_path = item["file_path"]
                safe_title = project.title.replace(" ", "_").replace("/", "_")
                arcname = f"{safe_title}_ortho.tif"
                zipf.write(file_path, arcname)

                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except: pass

        zip_size = os.path.getsize(temp_zip_path)

        if request.custom_filename:
            zip_filename = request.custom_filename
            if not zip_filename.lower().endswith('.zip'):
                zip_filename += ".zip"
        else:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_filename = f"batch_export_{timestamp}.zip"

        _pending_downloads[download_id] = {
            "file_path": temp_zip_path,
            "filename": zip_filename,
            "media_type": "application/zip",
            "file_size": zip_size,
            "created_at": time.time(),
        }

        return {
            "download_id": download_id,
            "filename": zip_filename,
            "file_size": zip_size,
        }

    except Exception as e:
        try:
            os.unlink(temp_zip_path)
        except:
            pass
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to prepare download: {str(e)}",
        )


@router.get("/batch/{download_id}")
async def get_prepared_download(
    download_id: str,
):
    # 인증 불필요 - download_id 자체가 임시 토큰 역할
    # (prepare 단계에서 이미 권한 확인됨)
    """
    준비된 파일을 직접 다운로드합니다.
    브라우저가 직접 파일을 다운로드하므로 메모리 문제가 없습니다.
    """
    info = _pending_downloads.get(download_id)

    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or expired",
        )

    file_path = info["file_path"]

    if not os.path.exists(file_path):
        _pending_downloads.pop(download_id, None)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="File not found",
        )

    encoded_filename = quote(info["filename"])

    async def iter_file_and_cleanup():
        try:
            async with aiofiles.open(file_path, 'rb') as f:
                while chunk := await f.read(8 * 1024 * 1024):  # 8MB chunks
                    yield chunk
        finally:
            # 다운로드 완료 후 정리
            _pending_downloads.pop(download_id, None)
            if file_path.startswith(tempfile.gettempdir()):
                try:
                    os.unlink(file_path)
                except:
                    pass

    return StreamingResponse(
        iter_file_and_cleanup(),
        headers={
            "Content-Length": str(info["file_size"]),
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
        media_type=info["media_type"],
    )
