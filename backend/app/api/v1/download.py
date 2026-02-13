"""Download API endpoints with resumable download support."""
import os
import re
from urllib.parse import quote
from uuid import UUID
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
from app.utils.checksum import calculate_file_checksum_async as calculate_file_checksum
from app.utils.gdal import extract_gsd_and_crs as get_source_gsd_and_crs

router = APIRouter(prefix="/download", tags=["Download"])


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
    
    # Check local file first, then fall back to storage backend
    file_path = job.result_path
    temp_file_path = None

    if file_path and os.path.exists(file_path):
        file_size = os.path.getsize(file_path)
    else:
        # Fallback: try Project.ortho_path in storage, then job.result_path as key
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        proj = project_result.scalar_one()

        storage = get_storage()
        storage_key = None

        if proj.ortho_path and storage.object_exists(proj.ortho_path):
            storage_key = proj.ortho_path
        elif file_path and storage.object_exists(file_path):
            storage_key = file_path

        if not storage_key:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result file not found (local or storage)",
            )

        # Local storage: use file directly without temp copy
        local_path = storage.get_local_path(storage_key)
        if local_path and os.path.exists(local_path):
            file_path = local_path
            file_size = os.path.getsize(file_path)
        else:
            # MinIO mode: download to temp file
            import tempfile as tf
            temp_file = tf.NamedTemporaryFile(delete=False, suffix='.tif')
            temp_file.close()
            storage.download_file(storage_key, temp_file.name)
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
                    except Exception: pass
        
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
                    except Exception: pass
        
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
        # Fallback to storage backend
        project_result = await db.execute(select(Project).where(Project.id == project_id))
        proj = project_result.scalar_one()
        storage = get_storage()
        storage_key = None
        if proj.ortho_path and storage.object_exists(proj.ortho_path):
            storage_key = proj.ortho_path
        elif file_path and storage.object_exists(file_path):
            storage_key = file_path
        if storage_key:
            # Local storage: use file directly for checksum calculation
            local_path = storage.get_local_path(storage_key)
            if local_path and os.path.exists(local_path):
                file_path = local_path
                file_size = os.path.getsize(file_path)
            else:
                file_size = storage.get_object_size(storage_key)
        else:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Result file not found",
            )

    checksum = job.result_checksum or (await calculate_file_checksum(file_path) if file_path and os.path.exists(file_path) else None)

    headers = {
        "Content-Length": str(file_size),
        "Accept-Ranges": "bytes",
        "X-File-Size": str(file_size),
    }
    if checksum:
        headers["X-File-Checksum"] = checksum

    return StreamingResponse(
        iter([]),
        headers=headers,
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
            except Exception:
                pass


def _warp_if_needed(source_path: str, target_crs: str, target_gsd_cm: float | None) -> str:
    """Re-project/resample a GeoTIFF if CRS or GSD differs. Returns final file path."""
    import subprocess

    # Validate CRS format to prevent command injection
    if not re.match(r'^EPSG:\d{4,5}$', target_crs):
        raise ValueError(f"Invalid CRS format: {target_crs}")

    try:
        source_gsd_m, source_epsg = get_source_gsd_and_crs(source_path)
        source_gsd_cm = source_gsd_m * 100 if source_gsd_m else None

        target_res = target_gsd_cm / 100.0 if target_gsd_cm else None

        crs_changed = (target_crs != source_epsg)
        gsd_changed = False
        if target_gsd_cm is not None and source_gsd_cm is not None:
            gsd_changed = abs(target_gsd_cm - source_gsd_cm) > 0.1

        if not crs_changed and not gsd_changed:
            return source_path

        print(f"Export warp: {source_epsg} -> {target_crs}, GSD: {source_gsd_cm} -> {target_gsd_cm} cm/px", flush=True)

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

        result = subprocess.run(warp_cmd, capture_output=True, text=True)

        if result.returncode == 0:
            # Clean up source if it was a temp file
            if source_path.startswith(tempfile.gettempdir()):
                try: os.unlink(source_path)
                except Exception: pass
            return warped_file.name
        else:
            print(f"gdalwarp failed: {result.stderr}", flush=True)
            try: os.unlink(warped_file.name)
            except Exception: pass
            return source_path

    except Exception as e:
        print(f"Re-projection failed: {e}", flush=True)
        return source_path


async def _collect_export_files(
    project_ids: list,
    target_crs: str,
    target_gsd_cm: float | None,
    current_user: User,
    db: AsyncSession,
) -> list[dict]:
    """Collect ortho files for batch export with optional re-projection.

    Returns list of {"project": Project, "file_path": str}.
    Caller is responsible for cleaning up temp files.
    """
    storage = get_storage()
    projects_with_files = []

    for project_id in project_ids:
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

        # Resolve to local file path
        source_path = None
        local_src = storage.get_local_path(ortho_path)
        if local_src and os.path.exists(local_src):
            source_path = local_src
        elif storage.object_exists(ortho_path):
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

        final_file_path = _warp_if_needed(source_path, target_crs, target_gsd_cm)
        projects_with_files.append({
            "project": project,
            "file_path": final_file_path,
        })

    return projects_with_files


def _make_export_filename(project, custom_filename: str | None, ext: str = ".tif") -> str:
    """Generate export filename from project title or custom name."""
    if custom_filename:
        name = custom_filename
        if not name.lower().endswith(ext) and not (ext == ".tif" and name.lower().endswith(".tiff")):
            name += ext
        return name
    safe_title = project.title.replace(" ", "_").replace("/", "_")
    return f"{safe_title}_ortho{ext}"


@router.post("/batch")
async def batch_download(
    request: BatchExportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Download multiple project orthoimages as a ZIP archive.
    Single project returns TIF directly; multiple projects return ZIP.
    """
    if not request.project_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No project IDs provided")
    if len(request.project_ids) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 20 projects allowed per batch export")

    projects_with_files = await _collect_export_files(
        request.project_ids, request.crs, request.gsd, current_user, db,
    )

    if not projects_with_files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No completed orthoimages found for the selected projects")

    # Single project: stream the TIF directly
    if len(projects_with_files) == 1:
        item = projects_with_files[0]
        file_path = item["file_path"]
        target_filename = _make_export_filename(item["project"], request.custom_filename)
        file_size = os.path.getsize(file_path)
        encoded_filename = quote(target_filename)

        async def iter_tif_file():
            try:
                async with aiofiles.open(file_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):
                        yield chunk
            finally:
                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except Exception: pass

        return StreamingResponse(
            iter_tif_file(),
            headers={
                "Content-Length": str(file_size),
                "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
            },
            media_type="image/tiff",
        )

    # Multi-project: create ZIP
    temp_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix='.zip').name
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            for item in projects_with_files:
                file_path = item["file_path"]
                arcname = _make_export_filename(item["project"], None)
                zipf.write(file_path, arcname)
                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except Exception: pass

        zip_size = os.path.getsize(temp_zip_path)

        async def iter_zip_file():
            try:
                async with aiofiles.open(temp_zip_path, 'rb') as f:
                    while chunk := await f.read(8 * 1024 * 1024):
                        yield chunk
            finally:
                try: os.unlink(temp_zip_path)
                except Exception: pass

        zip_filename = _make_export_filename(None, request.custom_filename, ".zip") if request.custom_filename else f"batch_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"
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
        try: os.unlink(temp_zip_path)
        except Exception: pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to create ZIP archive: {str(e)}")


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
    cleanup_old_downloads()

    if not request.project_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No project IDs provided")
    if len(request.project_ids) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 20 projects allowed per batch export")

    projects_with_files = await _collect_export_files(
        request.project_ids, request.crs, request.gsd, current_user, db,
    )

    if not projects_with_files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No completed orthoimages found for the selected projects")

    download_id = str(uuid.uuid4())

    # Single project: TIF
    if len(projects_with_files) == 1:
        item = projects_with_files[0]
        file_path = item["file_path"]
        target_filename = _make_export_filename(item["project"], request.custom_filename)
        file_size = os.path.getsize(file_path)

        _pending_downloads[download_id] = {
            "file_path": file_path,
            "filename": target_filename,
            "media_type": "image/tiff",
            "file_size": file_size,
            "created_at": time.time(),
        }
        return {"download_id": download_id, "filename": target_filename, "file_size": file_size}

    # Multi-project: ZIP
    temp_zip_path = tempfile.NamedTemporaryFile(delete=False, suffix='.zip').name
    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zipf:
            for item in projects_with_files:
                file_path = item["file_path"]
                arcname = _make_export_filename(item["project"], None)
                zipf.write(file_path, arcname)
                if file_path.startswith(tempfile.gettempdir()):
                    try: os.unlink(file_path)
                    except Exception: pass

        zip_size = os.path.getsize(temp_zip_path)
        zip_filename = _make_export_filename(None, request.custom_filename, ".zip") if request.custom_filename else f"batch_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        _pending_downloads[download_id] = {
            "file_path": temp_zip_path,
            "filename": zip_filename,
            "media_type": "application/zip",
            "file_size": zip_size,
            "created_at": time.time(),
        }
        return {"download_id": download_id, "filename": zip_filename, "file_size": zip_size}

    except Exception as e:
        try: os.unlink(temp_zip_path)
        except Exception: pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to prepare download: {str(e)}")


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
                except Exception:
                    pass

    return StreamingResponse(
        iter_file_and_cleanup(),
        headers={
            "Content-Length": str(info["file_size"]),
            "Content-Disposition": f"attachment; filename*=UTF-8''{encoded_filename}",
        },
        media_type=info["media_type"],
    )
