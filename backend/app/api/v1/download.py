"""Download API endpoints with resumable download support."""
import asyncio
import os
import re
import threading
import time
import logging
from urllib.parse import quote
from uuid import UUID
from typing import Any
from fastapi import APIRouter, Depends, Header, HTTPException, Request, status, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import aiofiles
from geoalchemy2.functions import ST_AsText

from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob
from app.auth.jwt import get_current_user, PermissionChecker, is_admin_role, verify_token
from app.services.storage import get_storage
from app.services.download_tokens import create_download_token, consume_download_token
from app.utils.checksum import calculate_file_checksum_async as calculate_file_checksum
from app.utils.gdal import extract_gsd_and_crs as get_source_gsd_and_crs

router = APIRouter(prefix="/download", tags=["Download"])
logger = logging.getLogger(__name__)
COG_LOOKUP_WARN_MS = float(os.getenv("COG_LOOKUP_WARN_MS", "1000"))


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


async def _validate_download_token_access(
    db: AsyncSession,
    token_payload: dict[str, Any],
    authorization: str | None = None,
) -> None:
    """Validate optional bearer token against download token scope.

    - If token has user_id, authenticated user must match same user.
    - If token has organization_id, authenticated non-admin user must be in same org.
    - If no Authorization header is provided, download remains allowed for public one-time links.
    """
    token_user_id = token_payload.get("user_id")
    token_org_id = token_payload.get("organization_id")

    if not token_user_id and not token_org_id:
        return

    if not authorization or not authorization.startswith("Bearer "):
        return

    token = authorization.split(" ", 1)[1]
    try:
        payload = verify_token(token, "access")
    except HTTPException:
        return

    user_id = payload.get("sub")
    if not user_id:
        return

    result = await db.execute(select(User).where(User.id == user_id))
    current_user = result.scalar_one_or_none()
    if not current_user or not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or inactive user",
        )

    # If token was issued for a specific user, enforce exact match.
    if token_user_id and str(current_user.id) != str(token_user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Download token user mismatch",
        )

    # Enforce org boundary when token is scoped to organization.
    if token_org_id and not is_admin_role(current_user.role):
        if not current_user.organization_id or str(current_user.organization_id) != str(token_org_id):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Download token organization mismatch",
            )


def _build_cache_key(base_key: str, file_size: int, mtime: int | None = None) -> str:
    if mtime is None:
        return f"{base_key}:{file_size}"
    return f"{base_key}:{file_size}:{mtime}"


def _extract_bounds_from_wkt(bounds_wkt: str) -> list[float] | None:
    """Extract envelope from WKT polygon/point as [west, south, east, north]."""
    if not bounds_wkt:
        return None

    try:
        polygon_match = re.search(
            r"POLYGON\s*\(\(\s*(.+?)\s*\)\)",
            str(bounds_wkt),
            re.IGNORECASE | re.DOTALL,
        )
        if polygon_match:
            coords_str = polygon_match.group(1)
            lons = []
            lats = []
            for point in coords_str.split(","):
                parts = point.strip().split()
                if len(parts) < 2:
                    continue
                lon = float(parts[0])
                lat = float(parts[1])
                lons.append(lon)
                lats.append(lat)
            if lons and lats:
                return [min(lons), min(lats), max(lons), max(lats)]

        point_match = re.search(
            r"POINT\s*\(\s*([\d.+-]+)\s+([\d.+-]+)\s*\)",
            str(bounds_wkt),
            re.IGNORECASE,
        )
        if point_match:
            lon = float(point_match.group(1))
            lat = float(point_match.group(2))
            return [lon, lat, lon, lat]

    except Exception:
        pass

    return None


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

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
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
        storage = get_storage()
        storage_key = None

        if scoped_project.ortho_path and storage.object_exists(scoped_project.ortho_path):
            storage_key = scoped_project.ortho_path
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
    project = scoped_project
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

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
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
        storage = get_storage()
        storage_key = None
        if scoped_project.ortho_path and storage.object_exists(scoped_project.ortho_path):
            storage_key = scoped_project.ortho_path
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
    response: Response,
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
    start_time = time.perf_counter()

    def _build_response(url: str, file_size: int, local: bool, cache_key: str) -> dict:
        latency_ms = round((time.perf_counter() - start_time) * 1000, 2)
        if latency_ms > COG_LOOKUP_WARN_MS:
            logger.warning(
                "cog_lookup_slow project_id=%s lookup_ms=%.2f threshold_ms=%.2f",
                project_id,
                latency_ms,
                COG_LOOKUP_WARN_MS,
            )
        return {
            "url": url,
            "local": local,
            "file_size": file_size,
            "bounds": _extract_bounds_from_wkt(bounds_wkt),
            "project_id": str(project_id),
            "lookup_ms": latency_ms,
            "cache_key": cache_key,
        }

    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    result = await db.execute(
        select(Project, ST_AsText(Project.bounds).label("bounds_wkt")).where(
            Project.id == project_id
        )
    )
    row = result.first()
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    project = row[0]
    bounds_wkt = row[1]

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
        cache_key = _build_cache_key(ortho_path, file_size, int(os.path.getmtime(local_path)))
        cog_response = _build_response(f"file://{local_path}", file_size, True, cache_key)
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
        response.headers["X-COG-Cache-Key"] = cache_key
        return cog_response

    # MinIO mode: check if object exists in storage
    if storage.object_exists(ortho_path):
        file_size = storage.get_object_size(ortho_path)
        s3_url = f"s3://{storage.bucket}/{ortho_path}"
        cache_key = _build_cache_key(ortho_path, file_size)
        cog_response = _build_response(s3_url, file_size, False, cache_key)
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
        response.headers["X-COG-Cache-Key"] = cache_key
        return cog_response

    # Check if it's a local file path (legacy processing jobs)
    if os.path.exists(ortho_path):
        file_size = os.path.getsize(ortho_path)
        cache_key = _build_cache_key(ortho_path, file_size, int(os.path.getmtime(ortho_path)))
        cog_response = _build_response(f"file://{ortho_path}", file_size, True, cache_key)
        response.headers["Cache-Control"] = "public, max-age=3600, immutable"
        response.headers["X-COG-Cache-Key"] = cache_key
        return cog_response

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Result file not found in storage",
    )


from pydantic import BaseModel
from typing import List
import zipfile
import tempfile
import time
from datetime import datetime


class BatchExportRequest(BaseModel):
    """Request model for batch export."""
    project_ids: List[UUID]
    format: str = "GeoTiff"
    crs: str = "EPSG:5186"
    gsd: float | None = None  # Planned GSD in cm/pixel (None = use original)
    custom_filename: str | None = None  # Optional custom filename for ZIP



def _warp_if_needed_sync(
    source_path: str,
    target_crs: str,
    target_gsd_cm: float | None,
    cancel_event: threading.Event | None = None,
) -> str:
    """Re-project/resample a GeoTIFF if CRS or GSD differs. Returns final file path.

    Runs gdalwarp via Popen so it can be terminated when cancel_event is set.
    """
    import subprocess

    # Validate CRS format to prevent command injection
    if not re.match(r'^EPSG:\d{4,5}$', target_crs):
        raise ValueError(f"Invalid CRS format: {target_crs}")

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

    proc = subprocess.Popen(warp_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        # Poll so we can react to cancellation
        while proc.poll() is None:
            if cancel_event and cancel_event.is_set():
                proc.terminate()
                proc.wait(timeout=10)
                print("Export warp cancelled by user", flush=True)
                try: os.unlink(warped_file.name)
                except Exception: pass
                raise _ExportCancelled()
            if cancel_event:
                cancel_event.wait(0.5)
            else:
                time.sleep(0.5)

        if proc.returncode == 0:
            # Clean up source if it was a temp file
            if source_path.startswith(tempfile.gettempdir()):
                try: os.unlink(source_path)
                except Exception: pass
            return warped_file.name
        else:
            stderr = proc.stderr.read().decode(errors="replace") if proc.stderr else ""
            print(f"gdalwarp failed (rc={proc.returncode}): {stderr}", flush=True)
            try: os.unlink(warped_file.name)
            except Exception: pass
            raise RuntimeError(f"좌표계 변환 실패: {stderr[:200]}")
    except _ExportCancelled:
        raise
    except RuntimeError:
        raise
    except Exception:
        proc.kill()
        proc.wait()
        try: os.unlink(warped_file.name)
        except Exception: pass
        raise


class _ExportCancelled(Exception):
    """Raised when the user cancels an export."""
    pass


async def _collect_export_files(
    project_ids: list,
    target_crs: str,
    target_gsd_cm: float | None,
    current_user: User,
    db: AsyncSession,
    cancel_event: threading.Event | None = None,
) -> list[dict]:
    """Collect ortho files for batch export with optional re-projection.

    Returns list of {"project": Project, "file_path": str}.
    Caller is responsible for cleaning up temp files.
    """
    storage = get_storage()
    projects_with_files = []

    for project_id in project_ids:
        if cancel_event and cancel_event.is_set():
            break

        permission_checker = PermissionChecker("view")
        if not await permission_checker.check(str(project_id), current_user, db):
            continue

        project = await _get_scoped_project(project_id, current_user, db)
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

        final_file_path = await asyncio.to_thread(
            _warp_if_needed_sync, source_path, target_crs, target_gsd_cm, cancel_event,
        )
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
    http_request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    파일을 준비하고 다운로드 ID를 반환합니다.
    실제 다운로드는 GET /batch/{download_id}로 수행합니다.
    이 방식은 브라우저 메모리 문제를 방지합니다.
    """
    if not request.project_ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No project IDs provided")
    if len(request.project_ids) > 20:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Maximum 20 projects allowed per batch export")

    # Cancel event: set when the client disconnects (user clicks cancel)
    cancel_event = threading.Event()

    async def _watch_disconnect():
        while not cancel_event.is_set():
            if await http_request.is_disconnected():
                cancel_event.set()
                return
            await asyncio.sleep(0.5)

    watch_task = asyncio.create_task(_watch_disconnect())

    projects_with_files = []
    try:
        projects_with_files = await _collect_export_files(
            request.project_ids, request.crs, request.gsd, current_user, db,
            cancel_event=cancel_event,
        )
    except _ExportCancelled:
        # Clean up any temp files created before cancellation
        for item in projects_with_files:
            fp = item.get("file_path", "")
            if fp.startswith(tempfile.gettempdir()):
                try: os.unlink(fp)
                except Exception: pass
        return Response(status_code=499)  # Client Closed Request
    finally:
        cancel_event.set()
        watch_task.cancel()

    if not projects_with_files:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No completed orthoimages found for the selected projects")

    # Single project: TIF
    if len(projects_with_files) == 1:
        item = projects_with_files[0]
        file_path = item["file_path"]
        target_filename = _make_export_filename(item["project"], request.custom_filename)
        file_size = os.path.getsize(file_path)

        token = await create_download_token(
            file_path=file_path,
            filename=target_filename,
            media_type="image/tiff",
            file_size=file_size,
            organization_id=str(current_user.organization_id) if current_user.organization_id else None,
            project_ids=[str(item["project"].id)],
            user_id=str(current_user.id),
        )
        return {
            "download_id": token,
            "filename": target_filename,
            "file_size": file_size,
        }

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

        token = await create_download_token(
            file_path=temp_zip_path,
            filename=zip_filename,
            media_type="application/zip",
            file_size=zip_size,
            organization_id=str(current_user.organization_id) if current_user.organization_id else None,
            project_ids=[str(item["project"].id) for item in projects_with_files],
            user_id=str(current_user.id),
        )
        return {"download_id": token, "filename": zip_filename, "file_size": zip_size}

    except Exception as e:
        try: os.unlink(temp_zip_path)
        except Exception: pass
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Failed to prepare download: {str(e)}")


@router.get("/batch/{download_id}")
async def get_prepared_download(
    download_id: str,
    authorization: str | None = Header(default=None, alias="Authorization"),
    db: AsyncSession = Depends(get_db),
):
    """
    준비된 파일을 직접 다운로드합니다.
    브라우저가 직접 파일을 다운로드하므로 메모리 문제가 없습니다.
    """
    info = await consume_download_token(download_id)
    if info:
        await _validate_download_token_access(
            db,
            info,
            authorization=authorization,
        )

    if not info:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Download not found or expired",
        )

    file_path = info["file_path"]

    if not os.path.exists(file_path):
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


# ── 도엽 클립/머지 API ──

class ClipRequest(BaseModel):
    """도엽 클립 내보내기 요청."""
    project_ids: List[UUID]
    sheet_ids: List[str]  # MAPIDCD_NO 목록
    scale: int = 5000
    crs: str = "EPSG:5186"
    gsd: float | None = None


class MergeRequest(BaseModel):
    """도엽 머지 내보내기 요청."""
    project_ids: List[UUID]
    sheet_id: str  # 단일 도엽
    scale: int = 5000
    crs: str = "EPSG:5186"
    gsd: float | None = None


def _get_sheet_bounds_in_crs(sheet_info: dict, target_crs: str) -> tuple:
    """도엽 bounds(WGS84)를 타겟 CRS로 변환하여 (minx, miny, maxx, maxy) 반환."""
    from pyproj import Transformer

    b = sheet_info["b4326"]  # (minlat, minlon, maxlat, maxlon)

    if target_crs == "EPSG:4326":
        # WGS84: x=lon, y=lat
        return (b[1], b[0], b[3], b[2])

    transformer = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
    x_min, y_min = transformer.transform(b[1], b[0])  # lon, lat → x, y
    x_max, y_max = transformer.transform(b[3], b[2])
    return (min(x_min, x_max), min(y_min, y_max), max(x_min, x_max), max(y_min, y_max))


def _clip_to_extent(source_path: str, target_crs: str, extent: tuple,
                    target_gsd_cm: float | None) -> str | None:
    """정사영상을 주어진 extent로 클립한다. 결과 임시 파일 경로 반환."""
    import subprocess

    if not re.match(r'^EPSG:\d{4,5}$', target_crs):
        raise ValueError(f"Invalid CRS format: {target_crs}")

    out_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tif')
    out_file.close()

    minx, miny, maxx, maxy = extent
    cmd = [
        "gdalwarp",
        "-t_srs", target_crs,
        "-te", str(minx), str(miny), str(maxx), str(maxy),
        "-r", "bilinear",
        "-overwrite",
        "-co", "COMPRESS=LZW",
        "-co", "TILED=YES",
    ]

    if target_gsd_cm:
        target_res = target_gsd_cm / 100.0
        if target_crs == "EPSG:4326":
            deg_res = target_res / 111320.0
            cmd.extend(["-tr", f"{deg_res:.12f}", f"{deg_res:.12f}"])
        else:
            cmd.extend(["-tr", str(target_res), str(target_res)])

    cmd.extend([source_path, out_file.name])

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        try:
            os.unlink(out_file.name)
        except Exception:
            pass
        print(f"[clip] gdalwarp failed: {result.stderr}", flush=True)
        return None

    # 빈 파일 체크 (extent가 정사영상 범위 밖인 경우)
    if os.path.getsize(out_file.name) < 1000:
        try:
            os.unlink(out_file.name)
        except Exception:
            pass
        return None

    return out_file.name


@router.post("/clip")
async def clip_export(
    request: ClipRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """도엽 단위로 정사영상을 클립하여 다운로드한다."""
    from app.api.v1.sheets import _get_index

    if not request.project_ids or not request.sheet_ids:
        raise HTTPException(status_code=400, detail="project_ids와 sheet_ids가 필요합니다.")
    if len(request.sheet_ids) > 50:
        raise HTTPException(status_code=400, detail="최대 50개 도엽까지 선택 가능합니다.")

    idx = _get_index(request.scale)
    if not idx["loaded"]:
        raise HTTPException(status_code=404, detail=f"1:{request.scale} 도엽 데이터가 없습니다.")

    # 도엽 정보 조회
    sheet_infos = {}
    for sid in request.sheet_ids:
        if sid in idx["sheets"]:
            sheet_infos[sid] = idx["sheets"][sid]
    if not sheet_infos:
        raise HTTPException(status_code=404, detail="유효한 도엽이 없습니다.")

    # 프로젝트 COG 파일 수집
    projects_with_files = await _collect_export_files(
        request.project_ids, "EPSG:4326", None, current_user, db,
    )
    if not projects_with_files:
        raise HTTPException(status_code=404, detail="정사영상이 있는 프로젝트가 없습니다.")

    # 클립 실행
    clipped_files = []
    temp_files = []
    try:
        for sid, sinfo in sheet_infos.items():
            extent = _get_sheet_bounds_in_crs(sinfo, request.crs)
            for item in projects_with_files:
                source = item["file_path"]
                clipped = _clip_to_extent(source, request.crs, extent, request.gsd)
                if clipped:
                    safe_title = re.sub(r'[^\w\-]', '_', item["project"].title)
                    arcname = f"{sid}_{safe_title}.tif"
                    clipped_files.append({"path": clipped, "arcname": arcname})
                    temp_files.append(clipped)

        if not clipped_files:
            raise HTTPException(status_code=404, detail="클립 결과가 없습니다. 도엽이 정사영상 범위 밖일 수 있습니다.")

        # 단일 파일: TIF 직접, 다중: ZIP
        if len(clipped_files) == 1:
            cf = clipped_files[0]
            file_size = os.path.getsize(cf["path"])
            token = await create_download_token(
                file_path=cf["path"],
                filename=cf["arcname"],
                media_type="image/tiff",
                file_size=file_size,
                organization_id=str(current_user.organization_id) if current_user.organization_id else None,
                project_ids=[str(p["project"].id) for p in projects_with_files],
                user_id=str(current_user.id),
            )
            return {"download_id": token, "filename": cf["arcname"], "file_size": file_size}

        # ZIP 패킹
        temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix='.zip')
        temp_zip.close()
        temp_files.append(temp_zip.name)

        with zipfile.ZipFile(temp_zip.name, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
            for cf in clipped_files:
                zf.write(cf["path"], cf["arcname"])

        zip_size = os.path.getsize(temp_zip.name)
        zip_filename = f"clip_{request.scale}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.zip"

        # 개별 클립 파일 정리 (ZIP에 넣었으므로)
        for cf in clipped_files:
            try:
                os.unlink(cf["path"])
            except Exception:
                pass

        token = await create_download_token(
            file_path=temp_zip.name,
            filename=zip_filename,
            media_type="application/zip",
            file_size=zip_size,
            organization_id=str(current_user.organization_id) if current_user.organization_id else None,
            project_ids=[str(p["project"].id) for p in projects_with_files],
            user_id=str(current_user.id),
        )
        return {"download_id": token, "filename": zip_filename, "file_size": zip_size}

    except HTTPException:
        raise
    except Exception as e:
        # 임시 파일 정리
        for tf in temp_files:
            try:
                os.unlink(tf)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"클립 처리 실패: {str(e)}")
    finally:
        # _collect_export_files에서 만든 temp 파일 정리
        for item in projects_with_files:
            fp = item["file_path"]
            if fp.startswith(tempfile.gettempdir()):
                try:
                    os.unlink(fp)
                except Exception:
                    pass


@router.post("/merge")
async def merge_export(
    request: MergeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """여러 프로젝트의 정사영상을 하나의 도엽 범위로 합쳐서 다운로드한다."""
    import subprocess
    from app.api.v1.sheets import _get_index

    if not request.project_ids or len(request.project_ids) < 2:
        raise HTTPException(status_code=400, detail="머지는 2개 이상의 프로젝트가 필요합니다.")

    idx = _get_index(request.scale)
    if not idx["loaded"]:
        raise HTTPException(status_code=404, detail=f"1:{request.scale} 도엽 데이터가 없습니다.")

    if request.sheet_id not in idx["sheets"]:
        raise HTTPException(status_code=404, detail=f"도엽 {request.sheet_id}을 찾을 수 없습니다.")

    sinfo = idx["sheets"][request.sheet_id]
    extent = _get_sheet_bounds_in_crs(sinfo, request.crs)

    # 프로젝트 COG 파일 수집
    projects_with_files = await _collect_export_files(
        request.project_ids, "EPSG:4326", None, current_user, db,
    )
    if len(projects_with_files) < 2:
        raise HTTPException(status_code=404, detail="머지할 수 있는 정사영상이 2개 미만입니다.")

    temp_files = []
    try:
        # 각 프로젝트를 도엽 범위로 클립
        clipped_paths = []
        for item in projects_with_files:
            clipped = _clip_to_extent(item["file_path"], request.crs, extent, request.gsd)
            if clipped:
                clipped_paths.append(clipped)
                temp_files.append(clipped)

        if len(clipped_paths) < 2:
            raise HTTPException(status_code=404, detail="머지할 수 있는 클립 결과가 2개 미만입니다.")

        # gdalwarp로 모자이킹 (마지막 입력 우선)
        merged_file = tempfile.NamedTemporaryFile(delete=False, suffix='.tif')
        merged_file.close()
        temp_files.append(merged_file.name)

        minx, miny, maxx, maxy = extent
        merge_cmd = [
            "gdalwarp",
            "-t_srs", request.crs,
            "-te", str(minx), str(miny), str(maxx), str(maxy),
            "-r", "bilinear",
            "-overwrite",
            "-co", "COMPRESS=LZW",
            "-co", "TILED=YES",
        ]

        if request.gsd:
            target_res = request.gsd / 100.0
            if request.crs == "EPSG:4326":
                deg_res = target_res / 111320.0
                merge_cmd.extend(["-tr", f"{deg_res:.12f}", f"{deg_res:.12f}"])
            else:
                merge_cmd.extend(["-tr", str(target_res), str(target_res)])

        merge_cmd.extend(clipped_paths)
        merge_cmd.append(merged_file.name)

        result = subprocess.run(merge_cmd, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            raise Exception(f"gdalwarp merge failed: {result.stderr}")

        # 클립 임시 파일 정리
        for cp in clipped_paths:
            try:
                os.unlink(cp)
            except Exception:
                pass

        file_size = os.path.getsize(merged_file.name)
        filename = f"merge_{request.sheet_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.tif"

        token = await create_download_token(
            file_path=merged_file.name,
            filename=filename,
            media_type="image/tiff",
            file_size=file_size,
            organization_id=str(current_user.organization_id) if current_user.organization_id else None,
            project_ids=[str(p["project"].id) for p in projects_with_files],
            user_id=str(current_user.id),
        )
        return {"download_id": token, "filename": filename, "file_size": file_size}

    except HTTPException:
        raise
    except Exception as e:
        for tf in temp_files:
            try:
                os.unlink(tf)
            except Exception:
                pass
        raise HTTPException(status_code=500, detail=f"머지 처리 실패: {str(e)}")
    finally:
        for item in projects_with_files:
            fp = item["file_path"]
            if fp.startswith(tempfile.gettempdir()):
                try:
                    os.unlink(fp)
                except Exception:
                    pass
