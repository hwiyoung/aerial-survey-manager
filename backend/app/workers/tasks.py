"""Celery application and async tasks."""
import logging
import os
import json
import shutil
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Optional
try:
    import resource
except Exception:
    resource = None

from celery import Celery

from app.config import get_settings
from app.auth.jwt import create_internal_token
from app.errors import ERROR_SPECS, classify_processing_error, new_error_reference_id
from app.services.processing_logs import (
    append_processing_log,
    create_processing_error_bundle,
)
from app.services.image_previews import generate_thumbnail_gdal, generate_thumbnail_pil
from app.utils.checksum import calculate_file_checksum
from app.utils.formatting import format_elapsed as _fmt_elapsed
from app.utils.gdal import extract_bounds_wkt as get_orthophoto_bounds
from app.utils.storage_paths import (
    is_numbered_orthomosaic_variant,
    legacy_processing_work_dir,
    numbered_orthomosaic_key,
    orthomosaic_key,
    processing_exclusion_path,
    processing_images_dir,
    processing_log_path,
    processing_metadata_path,
    processing_status_path,
    processing_work_dir,
    project_root_dir,
    source_images_prefix,
    source_thumbnail_key,
    source_thumbnail_prefix,
)

settings = get_settings()
logger = logging.getLogger(__name__)

QUEUE_WAIT_WARN_SECONDS = float(os.getenv("PROCESSING_QUEUE_WAIT_WARN_SECONDS", "300"))
PROCESSING_TOTAL_WARN_SECONDS = float(os.getenv("PROCESSING_TOTAL_WARN_SECONDS", "7200"))
PROCESSING_MEMORY_WARN_MB = float(os.getenv("PROCESSING_MEMORY_WARN_MB", "8192"))
PROCESSING_ENGINE_QUEUE = os.getenv("PROCESSING_ENGINE_QUEUE", "gpu-engine")
ENABLE_EXTERNAL_COG_INGEST = (
    os.getenv("ENABLE_EXTERNAL_COG_INGEST", "false").strip().lower() == "true"
)
CANCELLED_PROCESSING_MESSAGE = "처리가 취소되었습니다."


class ProcessingCancelled(Exception):
    """Raised when the worker notices that the DB job was cancelled."""


def _is_processing_redelivery(
    *,
    job_status: str,
    expected_task_id: str | None,
    request_task_id: str | None,
    delivery_info: dict | None,
) -> bool:
    """Return True only for Redis redelivery of the same interrupted job."""
    return bool(
        job_status == "processing"
        and expected_task_id
        and request_task_id
        and expected_task_id == request_task_id
        and (delivery_info or {}).get("redelivered")
    )


def _camera_pixel_size_to_mm(value) -> float | None:
    """Return camera pixel size in millimeters.

    CameraModel.pixel_size is populated from io.csv in micrometers. Some
    hand-entered or future-corrected records may already be in millimeters, so
    values below 0.1 are treated as mm for backward compatibility.
    """
    if value is None:
        return None
    try:
        pixel_size = float(value)
    except (TypeError, ValueError):
        return None
    if pixel_size <= 0:
        return None
    return pixel_size / 1000.0 if pixel_size > 0.1 else pixel_size


# Create Celery application
celery_app = Celery(
    "aerial_survey",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)

# Celery configuration
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Seoul",
    enable_utc=True,
    task_track_started=True,
    task_default_queue="celery",
    result_expires=86400,
    # 기본 visibility_timeout(1시간)이 만료되면 Redis가 task를 재전달함.
    # 2000장 처리 시 24시간+, 여러 프로젝트 대기 시 합산 대기시간을 고려해 7일로 설정.
    broker_transport_options={"visibility_timeout": 604800},
    # prefetch=1: worker가 queue에서 1개 task만 가져옴.
    # prefetch>1이면 대기 task들도 Redis에서 in-flight로 카운트되어 visibility_timeout 소비.
    worker_prefetch_multiplier=1,
    broker_connection_retry_on_startup=True,
    task_routes={
        "app.workers.tasks.process_orthophoto": {"queue": PROCESSING_ENGINE_QUEUE},
        # 썸네일 태스크는 전용 워커에서 처리 (처리 중에도 동시 실행)
        "app.workers.tasks.generate_thumbnail": {"queue": "thumbnail"},
        "app.workers.tasks.regenerate_missing_thumbnails": {"queue": "thumbnail"},
        "app.workers.tasks.delete_project_data": {"queue": "celery"},
        "app.workers.tasks.delete_source_images": {"queue": "celery"},
        "app.workers.tasks.inject_external_cog": {"queue": "celery"},
        "app.workers.tasks.inspect_worker_gpu": {"queue": PROCESSING_ENGINE_QUEUE},
        "app.workers.tasks.prepare_clip_export": {"queue": "celery"},
    },
)


def _update_clip_export_job(job_id: str, **values) -> str | None:
    """Update a clip job and return its current status."""

    from app.models.project import ClipExportJob
    from app.utils.db import sync_db_session

    with sync_db_session() as db:
        job = db.query(ClipExportJob).filter(ClipExportJob.id == job_id).first()
        if not job:
            return None
        for key, value in values.items():
            setattr(job, key, value)
        db.commit()
        return job.status


@celery_app.task(
    bind=True,
    name="app.workers.tasks.prepare_clip_export",
    acks_late=True,
    reject_on_worker_lost=True,
)
def prepare_clip_export(
    self,
    job_id: str,
    sources: list[dict],
    sheet_bounds: list[list[float]],
):
    """Create one union clip in the shared export volume."""

    from app.models.project import ClipExportJob
    from app.services.clip_exports import (
        ClipExportCancelled,
        InvalidCogSource,
        cleanup_expired_clip_exports,
        make_clip_filename,
        run_union_clip_export,
        select_available_clip_output_path,
        validate_cog_source,
    )
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    cleanup_expired_clip_exports()
    with sync_db_session() as db:
        job = db.query(ClipExportJob).filter(ClipExportJob.id == job_id).first()
        if not job or job.status in {"completed", "cancelled"}:
            return {"status": job.status if job else "missing", "job_id": job_id}
        job.status = "processing"
        job.progress = 5
        job.stage = "정사영상 확인 중"
        job.started_at = datetime.utcnow()
        db.commit()
        output_format = job.output_format
        output_crs = job.output_crs
        output_gsd = job.output_gsd
        output_filename = make_clip_filename(job.base_filename, output_format)

    job_dir = Path(settings.EXPORT_ROOT_PATH) / "clip-jobs" / job_id
    job_dir.mkdir(parents=True, exist_ok=True)
    output_path = job_dir / output_filename
    published_path: Path | None = None
    downloaded_sources: list[Path] = []
    source_paths: list[str] = []
    storage = get_storage()
    last_progress = 5

    def is_cancelled() -> bool:
        with sync_db_session() as db:
            current = db.query(ClipExportJob.status).filter(ClipExportJob.id == job_id).scalar()
            return current in (None, "cancelled")

    def on_progress(progress: int, stage: str) -> None:
        nonlocal last_progress
        bounded = max(last_progress, min(99, int(progress)))
        if bounded == last_progress and progress < 98:
            return
        last_progress = bounded
        _update_clip_export_job(job_id, progress=bounded, stage=stage)

    try:
        for index, source in enumerate(sources):
            if is_cancelled():
                raise ClipExportCancelled()
            object_name = source["ortho_path"]
            if os.path.isabs(object_name) and os.path.exists(object_name):
                local_path = object_name
            else:
                try:
                    local_path = storage.get_local_path(object_name)
                except (TypeError, ValueError):
                    local_path = None
            if local_path and os.path.exists(local_path):
                resolved = Path(local_path)
            elif not os.path.isabs(object_name) and storage.object_exists(object_name):
                resolved = job_dir / f".source-{index}.tif"
                storage.download_file(object_name, str(resolved))
                downloaded_sources.append(resolved)
            elif os.path.exists(object_name):
                resolved = Path(object_name)
            else:
                raise FileNotFoundError("clip source not found")
            validate_cog_source(str(resolved))
            source_paths.append(str(resolved))
            on_progress(8 + round((index + 1) / len(sources) * 10), "COG 검증 중")

        run_union_clip_export(
            source_paths=source_paths,
            sheet_bounds=sheet_bounds,
            target_crs=output_crs,
            target_gsd_cm=output_gsd,
            output_format=output_format,
            output_path=str(output_path),
            on_progress=on_progress,
            is_cancelled=is_cancelled,
        )
        if is_cancelled():
            raise ClipExportCancelled()
        with sync_db_session() as db:
            current = db.query(ClipExportJob).filter(ClipExportJob.id == job_id).first()
            if not current or current.status == "cancelled":
                raise ClipExportCancelled()

            bind = db.get_bind()
            dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
            if dialect_name == "postgresql":
                from sqlalchemy import text

                db.execute(
                    text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
                    {"lock_name": f"clip-export-filename:{output_filename}"},
                )

            published_path = select_available_clip_output_path(
                settings.EXPORT_ROOT_PATH,
                output_filename,
            )
            published_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.replace(published_path)

            current.status = "completed"
            current.progress = 100
            current.stage = "완료"
            current.output_filename = published_path.name
            current.result_path = str(published_path)
            current.result_size = published_path.stat().st_size
            current.completed_at = datetime.utcnow()
            current.error_code = None
            current.error_reference = None
            db.commit()
        return {
            "status": "completed",
            "job_id": job_id,
            "result_path": str(published_path),
        }
    except ClipExportCancelled:
        try:
            (published_path or output_path).unlink()
        except OSError:
            pass
        _update_clip_export_job(
            job_id,
            status="cancelled",
            stage="취소됨",
            completed_at=datetime.utcnow(),
        )
        return {"status": "cancelled", "job_id": job_id}
    except Exception as exc:
        error_code = (
            "EXPORT_SOURCE_NOT_FOUND"
            if isinstance(exc, FileNotFoundError)
            else "EXPORT_SOURCE_INVALID"
            if isinstance(exc, InvalidCogSource)
            else "EXPORT_FORMAT_INVALID"
            if isinstance(exc, ValueError)
            else "CLIP_PROCESSING_FAILED"
        )
        error_reference = new_error_reference_id()
        logger.exception(
            "clip_export_failed job_id=%s reference_id=%s",
            job_id,
            error_reference,
        )
        try:
            (published_path or output_path).unlink()
        except OSError:
            pass
        _update_clip_export_job(
            job_id,
            status="error",
            stage="오류",
            error_code=error_code,
            error_reference=error_reference,
            completed_at=datetime.utcnow(),
        )
        raise
    finally:
        for path in downloaded_sources:
            try:
                path.unlink()
            except OSError:
                pass
        shutil.rmtree(job_dir, ignore_errors=True)


def get_best_region_overlap(wkt_polygon: str, db_session) -> Optional[str]:
    """Find the region that has the most overlapping area with the given polygon."""
    from sqlalchemy import text
    try:
        # Query regions table to find the layer with maximum intersection area
        query = text("""
            SELECT layer
            FROM regions
            WHERE ST_Intersects(geom, ST_Transform(ST_GeomFromEWKT(:wkt), 5179))
            ORDER BY ST_Area(ST_Intersection(geom, ST_Transform(ST_GeomFromEWKT(:wkt), 5179))) DESC
            LIMIT 1
        """)
        result = db_session.execute(query, {"wkt": wkt_polygon}).fetchone()
        if result:
            return result[0]
    except Exception as e:
        print(f"Failed to find best region: {e}")
    return None


# ============================================================================
# Shared helpers (used by multiple tasks)
# ============================================================================

def _broadcast_ws(
    project_id: str,
    status: str,
    progress: int,
    message: str,
    *,
    error_code: str | None = None,
    error_action: str | None = None,
    error_reference: str | None = None,
):
    """Broadcast processing status update via WebSocket."""
    try:
        import httpx
        token = create_internal_token(
            "processing_broadcast",
            subject="worker",
            expires_delta=timedelta(minutes=5),
        )
        httpx.post(
            "http://api:8000/api/v1/processing/broadcast",
            params={"token": token},
            json={
                "project_id": project_id,
                "status": status,
                "progress": progress,
                "message": message,
                "error_code": error_code,
                "error_action": error_action,
                "error_reference": error_reference,
            },
            timeout=5.0
        )
    except Exception:
        pass


def _get_process_memory_mb() -> Optional[float]:
    """Get current process max RSS memory usage in MB."""
    if resource is None:
        return None

    try:
        max_rss = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
        # Linux ru_maxrss: KB, macOS/BSD: bytes
        if max_rss > 10_000_000:
            return round(max_rss / (1024 * 1024), 2)
        return round(max_rss / 1024, 2)
    except Exception:
        return None


@celery_app.task(name="app.workers.tasks.inspect_worker_gpu")
def inspect_worker_gpu():
    """Inspect GPU visibility from the worker-engine container."""
    from app.services.system_status import get_gpu_status

    return get_gpu_status()


def _convert_to_cog(input_path: str, output_path: str) -> None:
    """Convert a GeoTIFF to Cloud Optimized GeoTIFF using gdal_translate."""
    import subprocess
    gdal_cmd = [
        "gdal_translate", "-of", "COG",
        "-co", "COMPRESS=LZW",
        "-co", "BLOCKSIZE=1024",
        "-co", "OVERVIEW_RESAMPLING=AVERAGE",
        "-co", "BIGTIFF=YES",
        input_path, output_path
    ]
    subprocess.run(gdal_cmd, check=True, capture_output=True)


def _warp_to_cog(input_path: str, output_path: str, target_crs: str) -> None:
    """Warp a raster and write it as a Cloud Optimized GeoTIFF."""
    import subprocess

    gdal_cmd = [
        "gdalwarp",
        "-of", "COG",
        "-t_srs", target_crs,
        "-r", "bilinear",
        "-overwrite",
        "-multi",
        "-wo", "NUM_THREADS=ALL_CPUS",
        "-co", "COMPRESS=LZW",
        "-co", "BLOCKSIZE=1024",
        "-co", "OVERVIEW_RESAMPLING=AVERAGE",
        "-co", "BIGTIFF=YES",
        input_path,
        output_path,
    ]
    subprocess.run(gdal_cmd, check=True, capture_output=True)


def _assign_raster_crs(input_path: str, source_crs: str) -> None:
    """Assign a CRS tag without changing raster pixels or coordinates."""
    import subprocess

    gdal_cmd = [
        "gdal_edit.py",
        "-a_srs", source_crs,
        input_path,
    ]
    subprocess.run(gdal_cmd, check=True, capture_output=True)


def _is_cog_in_target_crs(path: Path | str, target_crs: str) -> bool:
    """Return True when a raster is already a COG in the requested CRS."""
    try:
        from osgeo import gdal, osr

        ds = gdal.Open(str(path), gdal.GA_ReadOnly)
        if ds is None:
            return False

        try:
            image_structure = ds.GetMetadata("IMAGE_STRUCTURE") or {}
            if image_structure.get("LAYOUT") != "COG":
                return False

            source_srs = osr.SpatialReference()
            if source_srs.ImportFromWkt(ds.GetProjection() or "") != 0:
                return False

            target_srs = osr.SpatialReference()
            if target_srs.SetFromUserInput(str(target_crs)) != 0:
                return False

            return bool(source_srs.IsSame(target_srs))
        finally:
            ds = None
    except Exception:
        return False


def _update_project_geo(project, bounds_wkt: str, db) -> None:
    """Update project bounds, area, and region from WKT polygon."""
    from sqlalchemy import text
    from app.utils.geo import extract_center_from_wkt, get_region_for_point_sync

    project.bounds = bounds_wkt

    # Calculate area using PostGIS (EPSG:5179 for Korea)
    try:
        area_query = text("SELECT ST_Area(ST_Transform(ST_GeomFromEWKT(:wkt), 5179)) / 1000000.0")
        area_result = db.execute(area_query, {"wkt": bounds_wkt}).scalar()
        project.area = area_result
    except Exception as area_err:
        print(f"Area calculation failed: {area_err}")

    # Auto-assign region based on overlap
    best_region = get_best_region_overlap(bounds_wkt, db)
    if best_region:
        project.region = best_region
    elif not project.region or project.region == "미지정":
        try:
            lon, lat = extract_center_from_wkt(bounds_wkt)
            if lon and lat:
                region = get_region_for_point_sync(db, lon, lat)
                if region:
                    project.region = region
        except Exception:
            pass


def _upload_cog_to_storage(cog_path, object_name: str, storage) -> Path:
    """Upload or move COG to storage backend. Returns final path."""
    from app.services.storage_local import LocalStorageBackend
    if isinstance(storage, LocalStorageBackend):
        storage.move_file(str(cog_path), object_name)
        return Path(storage.get_local_path(object_name))
    else:
        storage.upload_file(str(cog_path), object_name, "image/tiff")
        return cog_path


def _validate_cog(cog_path: Path):
    """Return immutable metadata after validating a completed COG."""
    checksum = calculate_file_checksum(str(cog_path))
    file_size = os.path.getsize(cog_path)
    bounds_wkt = get_orthophoto_bounds(str(cog_path))
    return checksum, file_size, bounds_wkt


def _validate_and_publish_cog(cog_path: Path, object_name: str, storage):
    """Validate a completed COG before making it visible in final storage."""
    checksum, file_size, bounds_wkt = _validate_cog(cog_path)
    _upload_cog_to_storage(cog_path, object_name, storage)
    return checksum, file_size, bounds_wkt


def _lock_orthomosaic_name_allocation(db, base_key: str) -> None:
    """Serialize allocation of one base filename on PostgreSQL.

    The transaction-scoped lock prevents two workers finishing projects with
    the same region/title from both selecting the same numbered filename.
    """
    bind = db.get_bind()
    dialect_name = getattr(getattr(bind, "dialect", None), "name", None)
    if dialect_name != "postgresql":
        return

    from sqlalchemy import text

    db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext(:lock_name))"),
        {"lock_name": f"orthomosaic-filename:{base_key}"},
    )


def _select_orthomosaic_target(
    db,
    project,
    base_key: str,
    storage,
) -> str:
    """Select a flat filename without overwriting another project's COG.

    The same project keeps its current base/numbered filename when reprocessed.
    Otherwise the first available PC-style name is returned: ``name.tif``,
    ``name (1).tif``, ``name (2).tif``, ... . DB-owned and untracked physical
    files are both treated as occupied.
    """
    from app.models.project import Project

    _lock_orthomosaic_name_allocation(db, base_key)

    other_project_paths = {
        str(row[0])
        for row in (
            db.query(Project.ortho_path)
            .filter(
                Project.id != project.id,
                Project.ortho_path.isnot(None),
            )
            .all()
        )
        if row[0]
    }

    current_key = str(project.ortho_path) if project.ortho_path else None
    if (
        is_numbered_orthomosaic_variant(current_key, base_key)
        and current_key not in other_project_paths
    ):
        return current_key

    for index in range(10_000):
        candidate = numbered_orthomosaic_key(base_key, index)
        if candidate in other_project_paths:
            continue
        if storage.object_exists(candidate):
            continue
        return candidate

    raise RuntimeError(
        "정사영상 최종 파일명을 만들 수 없습니다: "
        f"{base_key}의 중복 번호가 9,999개를 초과했습니다."
    )


def _prepare_images(storage, images, input_dir: Path, update_progress) -> int:
    """Symlink or download images for processing. Returns total source size.

    For local-import images (original_path is an absolute filesystem path),
    symlinks are created directly without going through the storage backend.
    For storage-managed images (relative object keys), the storage backend
    is used to resolve or download the file.
    """
    total_source_size = 0
    for i, image in enumerate(images):
        if image.file_size:
            total_source_size += image.file_size

        if image.original_path:
            target_path = input_dir / image.filename
            src_path = image.original_path

            # Determine if this is an absolute local path (local-import)
            # or a storage object key (e.g. "projects/{project_id}/source/images/file.jpg")
            if os.path.isabs(src_path):
                # Local-import: use the absolute path directly
                if not os.path.exists(src_path):
                    raise FileNotFoundError(
                        f"원본 이미지를 찾을 수 없습니다: {src_path} "
                        f"(이미지: {image.filename})"
                    )
                local_src = src_path
            else:
                # Storage-managed: resolve via storage backend
                local_src = storage.get_local_path(src_path)
                if not local_src or not os.path.exists(local_src):
                    try:
                        storage.download_file(src_path, str(target_path))
                    except FileNotFoundError:
                        raise FileNotFoundError(
                            f"저장소에서 이미지를 찾을 수 없습니다: {src_path} "
                            f"(이미지: {image.filename})"
                        )
                    download_progress = 5 + int((i + 1) / len(images) * 15)
                    update_progress(download_progress, f"{i + 1}/{len(images)} 이미지 준비 완료")
                    continue

            # Remove stale symlink/file from previous interrupted run
            if target_path.exists() or target_path.is_symlink():
                target_path.unlink()
            try:
                os.symlink(local_src, str(target_path))
            except OSError:
                import shutil
                shutil.copy2(local_src, str(target_path))

            download_progress = 5 + int((i + 1) / len(images) * 15)
            update_progress(download_progress, f"{i + 1}/{len(images)} 이미지 준비 완료")

    return total_source_size


def _image_merge_key(image_name: str) -> str:
    basename = os.path.basename(str(image_name or "").strip())
    return os.path.splitext(basename)[0].lower()


def _load_processing_excluded_image_keys(input_dir: Path) -> set[str]:
    exclusion_path = input_dir / ".excluded_images.txt"
    if not exclusion_path.exists():
        root_exclusion_path = input_dir.parent / ".excluded_images.txt"
        if not root_exclusion_path.exists():
            return set()
        exclusion_path = root_exclusion_path
    try:
        with open(exclusion_path, "r", encoding="utf-8") as f:
            return {
                line.strip().lower()
                for line in f
                if line.strip() and not line.lstrip().startswith("#")
            }
    except OSError:
        return set()


def _filter_excluded_processing_images(images, excluded_keys: set[str]):
    if not excluded_keys:
        return images
    return [
        image for image in images
        if _image_merge_key(image.filename) not in excluded_keys
    ]



# ============================================================================
# Main processing task
# ============================================================================

@celery_app.task(
    bind=True,
    name="app.workers.tasks.process_orthophoto",
    acks_late=True,
    reject_on_worker_lost=True,
)
def process_orthophoto(self, job_id: str, project_id: str, options: dict):
    """
    Main orthophoto processing task.

    Runs the configured Metashape GPU processing engine.
    """
    import asyncio
    from app.models.project import Project, ProcessingJob, Image
    from app.services.processing_router import processing_router
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    with sync_db_session() as db:
        # Lock in the same project -> job order used by the API. Only one
        # delivery is allowed to claim a queued job.
        project = (
            db.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )
        job = (
            db.query(ProcessingJob)
            .filter(
                ProcessingJob.id == job_id,
                ProcessingJob.project_id == project_id,
            )
            .with_for_update()
            .first()
        )

        if not job or not project:
            return {"status": "error", "message": "Job or project not found"}

        request_task_id = str(getattr(self.request, "id", "") or "")
        delivery_info = getattr(self.request, "delivery_info", {}) or {}
        if job.celery_task_id and request_task_id and job.celery_task_id != request_task_id:
            print(
                f"[process_orthophoto] Task ID mismatch for job {job_id}: "
                f"expected={job.celery_task_id} received={request_task_id}"
            )
            return {"status": "skipped", "message": "Task ID does not own this job"}

        is_redelivery = _is_processing_redelivery(
            job_status=job.status,
            expected_task_id=job.celery_task_id,
            request_task_id=request_task_id,
            delivery_info=delivery_info,
        )
        if job.status != "queued" and not is_redelivery:
            print(
                f"[process_orthophoto] Job {job_id} is {job.status}, "
                "so this delivery cannot claim it."
            )
            return {"status": "skipped", "message": f"Job is {job.status}"}

        if is_redelivery:
            print(
                f"[process_orthophoto] Reclaiming interrupted job {job_id} "
                f"task_id={request_task_id}"
            )

        try:
            queue_name = delivery_info.get("routing_key", "unknown")

            # Update status to processing
            job.status = "processing"
            job.started_at = job.started_at or datetime.utcnow()
            job.error_message = None
            job.error_code = None
            job.error_reference = None
            project.status = "processing"
            db.commit()

            queue_wait_seconds = None
            queued_at = job.queued_at or job.created_at
            if queued_at:
                queue_wait_seconds = max(
                    0.0,
                    (job.started_at - queued_at).total_seconds(),
                )
                print(
                    f"[Metrics] queue_wait_seconds={queue_wait_seconds:.2f} "
                    f"queue={queue_name} job_id={job_id} project_id={project_id}"
                )
                if queue_wait_seconds > QUEUE_WAIT_WARN_SECONDS:
                    print(
                        f"[SLO][WARN] queue_wait_seconds={queue_wait_seconds:.2f} "
                        f"exceeds_threshold={QUEUE_WAIT_WARN_SECONDS:.2f} "
                        f"queue={queue_name} job_id={job_id} project_id={project_id}"
                    )
            
            # Setup directories
            input_dir = processing_images_dir(project_id)
            output_dir = processing_work_dir(project_id)
            legacy_output_dir = legacy_processing_work_dir(project_id)
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            if legacy_output_dir.exists() and legacy_output_dir != output_dir:
                try:
                    shutil.rmtree(legacy_output_dir)
                    print(f"Cleaned up legacy processing directory: {legacy_output_dir}")
                except Exception as cleanup_err:
                    print(f"Failed to clean up legacy processing directory {legacy_output_dir}: {cleanup_err}")
            
            # Download images from storage
            storage = get_storage()
            images = db.query(Image).filter(
                Image.project_id == project_id,
                Image.upload_status == "completed",
            ).all()

            excluded_image_keys = _load_processing_excluded_image_keys(input_dir)
            if excluded_image_keys:
                before_count = len(images)
                images = _filter_excluded_processing_images(images, excluded_image_keys)
                skipped_count = before_count - len(images)
                print(
                    f"[Processing] EO preview excluded images skipped: "
                    f"{skipped_count}/{before_count} project_id={project_id}"
                )
            if not images:
                raise RuntimeError("처리 대상 이미지가 없습니다. EO 위치 preview의 제외 상태를 확인해주세요.")
            
            metadata_path = processing_metadata_path(project_id)
            if metadata_path.exists():
                compat_metadata_path = input_dir / "metadata.txt"
                if not compat_metadata_path.exists():
                    try:
                        os.symlink(metadata_path, compat_metadata_path)
                    except OSError:
                        import shutil
                        shutil.copy2(metadata_path, compat_metadata_path)

            exclusion_path = processing_exclusion_path(project_id)
            if exclusion_path.exists():
                compat_exclusion_path = input_dir / ".excluded_images.txt"
                if not compat_exclusion_path.exists():
                    try:
                        os.symlink(exclusion_path, compat_exclusion_path)
                    except OSError:
                        import shutil
                        shutil.copy2(exclusion_path, compat_exclusion_path)

            status_file = processing_status_path(project_id)
            status_file.parent.mkdir(parents=True, exist_ok=True)

            def write_status_file(
                progress: int,
                message: str,
                status_value: str = "processing",
                metrics: dict[str, object] | None = None,
                error_code: str | None = None,
                error_action: str | None = None,
                error_reference: str | None = None,
            ):
                try:
                    payload = {
                        "job_id": str(job.id),
                        "celery_task_id": job.celery_task_id,
                        "status": status_value,
                        "progress": progress,
                        "message": message,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    if metrics is not None:
                        payload["metrics"] = metrics
                    if error_code:
                        payload["error_code"] = error_code
                    if error_action:
                        payload["error_action"] = error_action
                    if error_reference:
                        payload["error_reference"] = error_reference
                    with open(status_file, "w", encoding="utf-8") as f:
                        json.dump(payload, f)
                except Exception:
                    pass

            def _is_cancelled_in_db() -> bool:
                try:
                    db.refresh(job)
                    db.refresh(project)
                except Exception:
                    return False
                return job.status == "cancelled" or project.status == "cancelled"

            def persist_cancelled_status(progress: int | None = None):
                cancel_progress = max(
                    0,
                    min(
                        100,
                        int(progress if progress is not None else (job.progress or project.progress or 0)),
                    ),
                )
                job.status = "cancelled"
                job.progress = cancel_progress
                job.completed_at = job.completed_at or datetime.utcnow()
                job.error_message = None
                job.error_code = None
                job.error_reference = None
                project.status = "cancelled"
                project.progress = cancel_progress
                db.commit()
                write_status_file(cancel_progress, CANCELLED_PROCESSING_MESSAGE, status_value="cancelled")
                _broadcast_ws(project_id, "cancelled", cancel_progress, CANCELLED_PROCESSING_MESSAGE)
                return {"status": "cancelled", "message": CANCELLED_PROCESSING_MESSAGE}

            def update_progress(progress, message=""):
                """Update progress in database, Celery state, and broadcast via WebSocket."""
                if _is_cancelled_in_db():
                    persist_cancelled_status()
                    raise ProcessingCancelled(CANCELLED_PROCESSING_MESSAGE)
                current = job.progress or 0
                if progress < current:
                    progress = current
                job.progress = progress
                project.progress = progress
                db.commit()
                write_status_file(progress, message, status_value="processing")
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "message": message}
                )
                _broadcast_ws(project_id, "processing", progress, message)

            phase_timings = []
            overall_start = time.time()

            # Phase 1: 이미지 준비
            t0 = time.time()
            is_local_storage = storage.get_local_path("") is not None
            msg = "이미지 심볼릭 링크 생성 중..." if is_local_storage else "저장소에서 이미지 다운로드 중..."
            update_progress(5, msg)

            project.source_size = _prepare_images(storage, images, input_dir, update_progress)
            db.commit()
            phase_timings.append(("이미지 준비", time.time() - t0))

            # Phase 2: 처리 엔진
            t0 = time.time()
            update_progress(20, "처리 엔진 시작 중...")
            
            # Define async progress callback
            async def progress_callback(progress, message):
                # Celery tasks are sync, so we just update directly
                scaled_progress = 20 + int(progress * 0.7)  # Scale to 20-90%
                update_progress(scaled_progress, message)
            
            # Run processing engine
            engine_name = options.get("engine", "metashape")
            options.setdefault("project_region", project.region)
            options.setdefault("project_title", project.title)

            # Interior Orientation override: a project is assumed to share a
            # single camera model across all its images, so we look up the first
            # image with a populated camera_model_id and forward its IO to the
            # engine. Missing fields → engine falls back to EXIF auto-calibration.
            if "camera_io" not in options:
                from app.models.project import CameraModel as _CameraModel
                first_image_cam = (
                    db.query(Image)
                    .filter(
                        Image.project_id == project_id,
                        Image.camera_model_id.isnot(None),
                    )
                    .first()
                )
                if first_image_cam and first_image_cam.camera_model_id:
                    cam = db.query(_CameraModel).filter(
                        _CameraModel.id == first_image_cam.camera_model_id
                    ).first()
                    pixel_size_mm = _camera_pixel_size_to_mm(cam.pixel_size if cam else None)
                    if cam and cam.focal_length and pixel_size_mm:
                        options["camera_io"] = {
                            "model_name": cam.name,
                            "focal_length_mm": float(cam.focal_length),
                            "pixel_size_mm": pixel_size_mm,
                            "pixel_size_um": float(cam.pixel_size),
                            "sensor_width_px": cam.sensor_width_px,
                            "sensor_height_px": cam.sensor_height_px,
                            "ppa_x_mm": float(cam.ppa_x) if cam.ppa_x is not None else 0.0,
                            "ppa_y_mm": float(cam.ppa_y) if cam.ppa_y is not None else 0.0,
                        }
                        print(
                            f"[Processing] IO override: {cam.name} "
                            f"focal={cam.focal_length}mm "
                            f"pixel={cam.pixel_size}µm/{pixel_size_mm:.6f}mm"
                        )
            print(f"[Processing] Engine dispatch: {engine_name} / queue={queue_name}")

            # This worker is the single final COG publisher. The router's
            # legacy auto-export path targets the same EXPORT_ROOT_PATH and
            # would otherwise create a second flat file before numbered-name
            # allocation runs.
            engine_options = dict(options)
            engine_options["auto_export"] = False
            
            # Run async processing in event loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            try:
                result_path = loop.run_until_complete(
                    processing_router.process(
                        engine_name=engine_name,
                        project_id=project_id,
                        input_dir=input_dir,
                        output_dir=output_dir,
                        options=engine_options,
                        progress_callback=progress_callback,
                    )
                )
            finally:
                loop.close()
            phase_timings.append(("처리 엔진", time.time() - t0))

            # Read result_gsd from status.json when provided by the engine
            status_json_path = output_dir / "status.json"
            if status_json_path.exists():
                try:
                    with open(status_json_path, "r") as f:
                        status_data = json.load(f)
                    if "result_gsd" in status_data:
                        job.result_gsd = status_data["result_gsd"]
                        print(f"📊 Result GSD saved to job: {job.result_gsd} cm/pixel")
                        db.commit()
                except Exception as e:
                    print(f"Failed to read result_gsd from status.json: {e}")

            # Phase 3: COG 변환/저장/정리
            t0 = time.time()
            update_progress(90, "클라우드 최적화 GeoTIFF 변환 중...")
            cog_path = output_dir / "result_cog.tif"
            target_ortho_crs = (
                options.get("export_target_crs")
                or settings.AUTO_EXPORT_TARGET_CRS
                or "EPSG:5186"
            )
            if str(target_ortho_crs).strip().isdigit():
                target_ortho_crs = f"EPSG:{str(target_ortho_crs).strip()}"
            base_result_object_name = orthomosaic_key(
                project_id,
                str(target_ortho_crs),
                region=project.region,
                title=project.title,
            )
            final_basename = Path(base_result_object_name).name
            orthomosaic_cog_path = output_dir / (
                f".{Path(final_basename).stem}.{job.id}.publishing.tif"
            )

            try:
                import shutil

                # Atomically close CRS reservation changes before touching the
                # output raster. API reserve/cancel calls lock the same row.
                job = (
                    db.query(ProcessingJob)
                    .filter(ProcessingJob.id == job_id)
                    .with_for_update()
                    .one()
                )
                correction_crs = (
                    job.crs_correction_source_crs
                    if job.crs_correction_status == "pending" and job.crs_correction_source_crs
                    else None
                )

                if correction_crs:
                    try:
                        job.crs_correction_status = "applying"
                        job.crs_correction_error = None
                        db.commit()
                        update_progress(91, f"좌표계 변경 적용 중... ({correction_crs})")

                        if result_path.exists():
                            if cog_path.exists():
                                cog_path.unlink()
                                print(f"Deleted stale COG before CRS correction: {cog_path}")
                            _assign_raster_crs(str(result_path), correction_crs)
                            _convert_to_cog(str(result_path), str(cog_path))
                        elif cog_path.exists():
                            print(
                                "⚠ result.tif is missing; assigning CRS directly to existing COG. "
                                f"path={cog_path}"
                            )
                            _assign_raster_crs(str(cog_path), correction_crs)
                        else:
                            raise RuntimeError("좌표계 변경을 적용할 정사영상 파일을 찾을 수 없습니다.")

                        job.crs_correction_status = "applied"
                        job.crs_correction_applied_at = datetime.utcnow()
                        job.crs_correction_error = None
                        db.commit()
                        print(f"✓ CRS correction applied before final COG/warp: {correction_crs}")
                    except Exception as correction_error:
                        job.crs_correction_status = "failed"
                        job.crs_correction_error = str(correction_error)
                        db.commit()
                        raise RuntimeError(f"좌표계 변경 적용 실패: {correction_error}") from correction_error
                else:
                    if job.crs_correction_status != "closed":
                        job.crs_correction_status = "closed"
                        job.crs_correction_error = None
                        db.commit()
                    # 엔진이 이미 COG를 생성한 경우 변환 스킵
                    if cog_path.exists():
                        print(f"COG already created by engine, skipping conversion: {cog_path}")
                    else:
                        _convert_to_cog(str(result_path), str(cog_path))

                # result.tif 조기 삭제 (COG 변환 완료 후 불필요)
                if result_path.exists() and result_path.name == "result.tif":
                    try:
                        result_path.unlink()
                        print(f"Deleted intermediate result.tif: {result_path}")
                    except Exception as del_err:
                        print(f"Failed to delete result.tif: {del_err}")

                update_progress(92, "결과물 COG 검증 중...")

                if _is_cog_in_target_crs(cog_path, str(target_ortho_crs)):
                    print(
                        f"COG already in target CRS ({target_ortho_crs}); "
                        "moving to final name without warp"
                    )
                    orthomosaic_cog_path.unlink(missing_ok=True)
                    shutil.move(str(cog_path), str(orthomosaic_cog_path))
                else:
                    _warp_to_cog(str(cog_path), str(orthomosaic_cog_path), str(target_ortho_crs))

                update_progress(94, "체크섬 및 영역 정보 확인 중...")
                checksum, file_size, bounds_wkt = _validate_cog(
                    orthomosaic_cog_path
                )
                if _is_cancelled_in_db():
                    return persist_cancelled_status()

                result_object_name = _select_orthomosaic_target(
                    db,
                    project,
                    base_result_object_name,
                    storage,
                )
                if result_object_name != base_result_object_name:
                    print(
                        "정사영상 파일명 중복을 피해 저장합니다: "
                        f"{Path(result_object_name).name}"
                    )
                _upload_cog_to_storage(
                    orthomosaic_cog_path,
                    result_object_name,
                    storage,
                )
                # Persist the filename reservation before releasing the
                # advisory transaction lock. The project remains processing
                # until final cleanup and geometry updates complete.
                project.ortho_path = result_object_name
                project.ortho_size = file_size
                job.result_path = result_object_name
                job.result_checksum = checksum
                job.result_size = file_size
                db.commit()

                # Clean up intermediate files in processing/.work/
                update_progress(96, "중간 파일 정리 중...")
                files_to_keep = {"status.json"}

                for item in output_dir.iterdir():
                    if item.name not in files_to_keep:
                        try:
                            if item.is_dir():
                                shutil.rmtree(item)
                                print(f"Cleaned up directory: {item}")
                            else:
                                item.unlink()
                                print(f"Cleaned up file: {item}")
                        except Exception as cleanup_err:
                            print(f"Failed to clean up {item}: {cleanup_err}")

                # Clean input directory (downloaded images / symlinks)
                if input_dir.exists():
                    try:
                        shutil.rmtree(input_dir)
                        print(f"Cleaned up input directory: {input_dir}")
                    except Exception as cleanup_err:
                        print(f"Failed to clean up input directory: {cleanup_err}")

            except Exception as cog_error:
                print(f"COG conversion failed: {cog_error}")
                raise
            phase_timings.append(("COG 검증/저장/정리", time.time() - t0))

            # Phase 4: 영역 정보 업데이트
            t0 = time.time()
            update_progress(98, "프로젝트 영역 정보 업데이트 중...")
            if bounds_wkt:
                _update_project_geo(project, bounds_wkt, db)

            phase_timings.append(("영역 정보 업데이트", time.time() - t0))

            # 전체 처리 시간 요약
            overall_elapsed = time.time() - overall_start
            total_elapsed_exceeded = overall_elapsed > PROCESSING_TOTAL_WARN_SECONDS
            queue_wait_exceeded = (
                queue_wait_seconds is not None and queue_wait_seconds > QUEUE_WAIT_WARN_SECONDS
            )
            memory_usage_mb = _get_process_memory_mb()
            memory_usage_exceeded = (
                memory_usage_mb is not None and memory_usage_mb > PROCESSING_MEMORY_WARN_MB
            )
            if total_elapsed_exceeded:
                print(
                    f"[SLO][WARN] total_elapsed_seconds={overall_elapsed:.2f} "
                    f"exceeds_threshold={PROCESSING_TOTAL_WARN_SECONDS:.2f} "
                    f"job_id={job_id} project_id={project_id}"
                )
            if memory_usage_exceeded:
                print(
                    f"[SLO][WARN] memory_usage_mb={memory_usage_mb:.2f} "
                    f"exceeds_threshold={PROCESSING_MEMORY_WARN_MB:.2f} "
                    f"job_id={job_id} project_id={project_id}"
                )
            summary_lines = []
            summary_lines.append(f"{'='*60}")
            summary_lines.append(f"전체 처리 완료 - 총 {_fmt_elapsed(overall_elapsed)}")
            if queue_wait_seconds is not None:
                summary_lines.append(f"큐 대기 시간            : {queue_wait_seconds:.2f}s")
            if memory_usage_mb is not None:
                summary_lines.append(f"최대 메모리 사용량      : {memory_usage_mb:.2f}MB")
            for idx, (phase_name, elapsed) in enumerate(phase_timings, 1):
                summary_lines.append(f"  {idx}. {phase_name:<20s}: {_fmt_elapsed(elapsed)}")
            summary_lines.append(f"{'='*60}")

            summary_text = "\n".join(summary_lines)
            print(summary_text)

            # .processing.log에도 요약 추가
            log_file_path = processing_log_path(project_id)
            try:
                append_processing_log(log_file_path, f"\n{summary_text}\n")
            except Exception:
                pass

            # Final status update
            if _is_cancelled_in_db():
                return persist_cancelled_status()

            job.status = "completed"
            job.progress = 100
            job.completed_at = datetime.utcnow()
            job.error_message = None
            job.error_code = None
            job.error_reference = None
            project.status = "completed"
            project.progress = 100
            project.ortho_path = result_object_name  # Store ortho path in project
            project.ortho_size = file_size
            job.result_path = result_object_name
            job.result_checksum = checksum
            job.result_size = file_size
            db.commit()
            final_metrics = {
                "queue_wait_seconds": queue_wait_seconds,
                "total_elapsed_seconds": round(overall_elapsed, 2),
                "slo": {
                    "queue_wait_warn_seconds": QUEUE_WAIT_WARN_SECONDS,
                    "total_elapsed_warn_seconds": PROCESSING_TOTAL_WARN_SECONDS,
                    "memory_warn_mb": PROCESSING_MEMORY_WARN_MB,
                    "queue_wait_exceeded": bool(queue_wait_exceeded),
                    "total_elapsed_exceeded": bool(total_elapsed_exceeded),
                    "memory_exceeded": bool(memory_usage_exceeded),
                },
                "memory_usage_mb": memory_usage_mb,
                "phase_elapsed_seconds": {
                    phase_name: round(elapsed, 2)
                    for phase_name, elapsed in phase_timings
                },
            }

            write_status_file(
                100,
                "Processing completed successfully",
                status_value="completed",
                metrics=final_metrics,
            )

            # Broadcast completion via WebSocket AFTER all DB updates
            _broadcast_ws(project_id, "completed", 100, "Processing completed successfully")

            return {
                "status": "completed",
                "result_path": result_object_name,
                "checksum": checksum,
                "size": file_size,
                "metrics": final_metrics,
            }
            
        except ProcessingCancelled:
            if "persist_cancelled_status" in locals():
                return persist_cancelled_status()
            raise

        except Exception as e:
            if "persist_cancelled_status" in locals() and _is_cancelled_in_db():
                return persist_cancelled_status()

            error_code = classify_processing_error(e)
            error_reference = new_error_reference_id()
            error_spec = ERROR_SPECS[error_code]
            user_friendly_error = error_spec.message
            logger.exception(
                "processing_failed reference_id=%s code=%s project_id=%s job_id=%s",
                error_reference,
                error_code,
                project_id,
                getattr(job, "id", None),
            )
            job.status = "error"
            job.error_message = user_friendly_error
            job.error_code = error_code
            job.error_reference = error_reference
            project.status = "error"
            db.commit()
            try:
                error_metrics = {
                    "error_code": error_code,
                    "error_reference": error_reference,
                }
                if 'phase_timings' in dir():
                    error_metrics["phase_elapsed_seconds"] = {
                        pn: round(el, 2) for pn, el in phase_timings
                    }
                write_status_file(
                    0,
                    user_friendly_error,
                    status_value="error",
                    metrics=error_metrics,
                    error_code=error_code,
                    error_action=error_spec.action,
                    error_reference=error_reference,
                )
            except NameError:
                pass  # write_status_file/phase_timings not yet defined (early failure)

            bundle_path = create_processing_error_bundle(
                project_id,
                error_reference,
                error_code=error_code,
                job_id=str(getattr(job, "id", "")) or None,
                technical_error=str(e),
            )
            if bundle_path:
                logger.error(
                    "processing_error_bundle_created reference_id=%s path=%s",
                    error_reference,
                    bundle_path,
                )

            _broadcast_ws(
                project_id,
                "error",
                0,
                user_friendly_error,
                error_code=error_code,
                error_action=error_spec.action,
                error_reference=error_reference,
            )

            raise


def _generate_thumbnail_gdal(source_path: str, dest_path: str, size: int = 256):
    """gdal_translate로 썸네일 생성 (오버뷰 활용 시 빠름).

    gdalinfo로 밴드 수/데이터 타입을 먼저 확인해 gdal_translate를 한 번만 실행.
    - 8-bit: -scale 생략 (파일을 한 번만 읽음)
    - 16-bit 이상: -scale 추가 (0-255 변환 필요)
    - 밴드 4개 이상: -b 1 -b 2 -b 3 으로 RGB만 추출
    """
    generate_thumbnail_gdal(source_path, dest_path, size)


def _generate_thumbnail_pil(source_path: str, dest_path: str, size: int = 256):
    """PIL로 썸네일 생성 (폴백, 전체 파일 읽음)."""
    generate_thumbnail_pil(source_path, dest_path, size)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_thumbnail",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def generate_thumbnail(self, image_id: str, force: bool = False):
    """Generate thumbnail for an uploaded image.

    Args:
        image_id: UUID of the image
        force: If True, regenerate even if thumbnail already exists
    """
    from app.models.project import Image
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    temp_path = None
    thumb_path = None

    with sync_db_session() as db:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image or not image.original_path:
            return {"status": "error", "message": "Image not found or no original path"}

        if image.thumbnail_path and not force:
            return {"status": "skipped", "message": "Thumbnail already exists"}

        storage = get_storage()

        # 원본 파일 경로 결정 (로컬 직접 접근 or 다운로드)
        if os.path.isabs(image.original_path) and os.path.exists(image.original_path):
            temp_path = image.original_path
        else:
            local_src = storage.get_local_path(image.original_path)
            if local_src and os.path.exists(local_src):
                temp_path = local_src
            else:
                temp_path = f"/tmp/{image_id}_{image.filename}"
                try:
                    storage.download_file(image.original_path, temp_path)
                except Exception as e:
                    print(f"Failed to download original image {image_id}: {e}")
                    raise

        thumb_path = f"/tmp/thumb_{image_id}_{image.filename}.jpg"

        try:
            # GDAL 우선 (오버뷰 활용 → 빠름), 실패 시 PIL 폴백
            try:
                _generate_thumbnail_gdal(temp_path, thumb_path)
            except Exception as gdal_err:
                print(f"[thumbnail] GDAL 실패 ({gdal_err}), PIL 폴백")
                _generate_thumbnail_pil(temp_path, thumb_path)

            thumb_object_name = source_thumbnail_key(image.project_id, image.filename)
            storage.upload_file(thumb_path, thumb_object_name, "image/jpeg")
            image.thumbnail_path = thumb_object_name
            db.commit()
            return {"status": "completed", "thumbnail_path": thumb_object_name}

        except Exception as e:
            print(f"Thumbnail generation failed for {image_id}: {e}")
            raise

        finally:
            is_temp = temp_path and temp_path.startswith("/tmp/")
            if is_temp and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except Exception:
                    pass
            if thumb_path and os.path.exists(thumb_path):
                try:
                    os.remove(thumb_path)
                except Exception:
                    pass


@celery_app.task(bind=True, name="app.workers.tasks.regenerate_missing_thumbnails")
def regenerate_missing_thumbnails(self, project_id: str = None):
    """Find and regenerate thumbnails for images that are missing them.

    Args:
        project_id: Optional - limit to specific project
    """
    from sqlalchemy import and_
    from app.models.project import Image
    from app.utils.db import sync_db_session

    with sync_db_session() as db:
        query = db.query(Image).filter(
            and_(
                Image.thumbnail_path.is_(None),
                Image.original_path.isnot(None),
                Image.upload_status == "completed",
            )
        )

        if project_id:
            query = query.filter(Image.project_id == project_id)

        images = query.all()

        triggered_count = 0
        for image in images:
            try:
                generate_thumbnail.delay(str(image.id))
                triggered_count += 1
            except Exception as e:
                print(f"Failed to trigger thumbnail for {image.id}: {e}")

        return {
            "status": "completed",
            "total_missing": len(images),
            "triggered": triggered_count,
        }


@celery_app.task(
    bind=True,
    name="app.workers.tasks.delete_project_data",
    acks_late=True,
    reject_on_worker_lost=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=300,
    max_retries=3,
)
def delete_project_data(
    self,
    project_id: str,
    original_paths: list[str] | None = None,
    ortho_path: str | None = None,
):
    """Delete all project-owned storage and local processing data."""
    from app.services.project_cleanup import cleanup_project_data

    return cleanup_project_data(
        project_id,
        original_paths or [],
        ortho_path,
    )


@celery_app.task(
    bind=True,
    name="app.workers.tasks.delete_source_images",
    acks_late=True,
    reject_on_worker_lost=True,
    max_retries=3,
)
def delete_source_images(self, project_id: str):
    """프로젝트의 원본 이미지를 스토리지에서 삭제하고 DB를 업데이트합니다."""
    from app.models.project import Project
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    with sync_db_session() as db:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"프로젝트를 찾을 수 없습니다: {project_id}"}

        storage = get_storage()
        deleted_count = 0

        try:
            # 원본 이미지 삭제
            images_prefix = source_images_prefix(project_id)
            objects = storage.list_objects(prefix=images_prefix, recursive=True)
            if objects:
                storage.delete_recursive(images_prefix)
                remaining_images = storage.list_objects(
                    prefix=images_prefix,
                    recursive=True,
                )
                if remaining_images:
                    raise RuntimeError(
                        f"원본 이미지 {len(remaining_images)}개가 삭제되지 않았습니다."
                    )
                deleted_count = len(objects)
                print(f"✓ 원본 이미지 삭제: {deleted_count}개 ({images_prefix})")
            else:
                print(f"ℹ 원본 이미지 없음: {images_prefix}")

            # 썸네일도 삭제
            thumbnails_prefix = source_thumbnail_prefix(project_id)
            thumb_objects = storage.list_objects(prefix=thumbnails_prefix, recursive=True)
            if thumb_objects:
                storage.delete_recursive(thumbnails_prefix)
                remaining_thumbnails = storage.list_objects(
                    prefix=thumbnails_prefix,
                    recursive=True,
                )
                if remaining_thumbnails:
                    raise RuntimeError(
                        f"썸네일 {len(remaining_thumbnails)}개가 삭제되지 않았습니다."
                    )
                print(f"✓ 썸네일 삭제: {len(thumb_objects)}개")

            freed_bytes = project.source_size or 0
            project.source_deleted = True
            db.commit()
            freed_gb = freed_bytes / (1024 * 1024 * 1024)
            print(f"✅ 프로젝트 {project_id} 원본 이미지 삭제 완료 ({freed_gb:.2f} GB 확보)")

            return {
                "status": "completed",
                "project_id": project_id,
                "deleted_count": deleted_count,
                "freed_bytes": freed_bytes,
            }

        except Exception as e:
            if self.request.retries < self.max_retries:
                countdown = min(60 * (2 ** self.request.retries), 300)
                print(
                    f"원본 이미지 삭제 재시도 예약: project={project_id} "
                    f"retry={self.request.retries + 1}/{self.max_retries} "
                    f"countdown={countdown}s error={e}"
                )
                raise self.retry(exc=e, countdown=countdown)

            project.source_deleted = False
            db.commit()
            print(f"✗ 원본 이미지 삭제 최종 실패 (source_deleted 복원): {e}")
            raise


@celery_app.task(
    bind=True,
    name="app.workers.tasks.inject_external_cog",
)
def inject_external_cog(self, project_id: str, source_path: str, gsd_cm: float = None, force: bool = False):
    """외부에서 생성한 COG/GeoTIFF를 프로젝트에 삽입하여 완료 상태로 만듭니다.

    Args:
        project_id: 프로젝트 UUID
        source_path: COG/GeoTIFF 파일 경로 (컨테이너 내부 경로)
        gsd_cm: GSD (cm/pixel), None이면 자동 추출
        force: True면 처리 중인 태스크를 강제 취소
    """
    import subprocess
    import shutil
    from app.models.project import Project, ProcessingJob
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    if not ENABLE_EXTERNAL_COG_INGEST:
        return {
            "status": "error",
            "message": "External COG ingest is disabled by policy. Set ENABLE_EXTERNAL_COG_INGEST=true to enable.",
        }

    source = Path(source_path)
    if not source.exists():
        return {"status": "error", "message": f"파일을 찾을 수 없습니다: {source_path}"}

    with sync_db_session() as db:
        project = (
            db.query(Project)
            .filter(Project.id == project_id)
            .with_for_update()
            .first()
        )
        if not project:
            return {"status": "error", "message": f"프로젝트를 찾을 수 없습니다: {project_id}"}

        # Check for running processing jobs
        running_job = db.query(ProcessingJob).filter(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status.in_(["scheduled", "queued", "processing"])
        ).with_for_update().first()

        if running_job:
            if not force:
                return {
                    "status": "error",
                    "message": f"처리 중인 작업이 있습니다 (job: {running_job.id}). --force 옵션으로 강제 취소할 수 있습니다."
                }
            # Cancel running Celery task
            if running_job.celery_task_id:
                celery_app.control.revoke(running_job.celery_task_id, terminate=True)
                print(f"⚠ Celery 태스크 취소: {running_job.celery_task_id}")
            running_job.status = "cancelled"
            running_job.error_message = "외부 COG 삽입으로 인해 취소됨"
            running_job.error_code = None
            running_job.error_reference = None
            db.commit()

        # Validate GeoTIFF via gdalinfo
        try:
            gdalinfo_result = subprocess.run(
                ["gdalinfo", "-json", str(source)],
                capture_output=True, text=True, check=True, timeout=120
            )
            gdalinfo_data = json.loads(gdalinfo_result.stdout)
        except subprocess.TimeoutExpired:
            return {"status": "error", "message": "gdalinfo 타임아웃 (120초 초과)"}
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": f"유효한 GeoTIFF가 아닙니다: {e.stderr}"}
        except (json.JSONDecodeError, Exception) as e:
            return {"status": "error", "message": f"gdalinfo 실행 실패: {e}"}

        # Extract GSD if not provided
        if gsd_cm is None:
            geo_transform = gdalinfo_data.get('geoTransform', [])
            if len(geo_transform) >= 2:
                pixel_size = abs(geo_transform[1])
                if pixel_size > 0:
                    coord_wkt = gdalinfo_data.get('coordinateSystem', {}).get('wkt', '')
                    if 'GEOGCS' in coord_wkt and 'PROJCS' not in coord_wkt:
                        # Geographic CRS (degrees) - 한국 위도 기준 근사 변환
                        gsd_cm = pixel_size * 111320 * 0.8 * 100
                        print(f"⚠ Geographic CRS 감지, GSD 근사값: {gsd_cm:.2f} cm/pixel (정확한 값은 --gsd 옵션 사용)")
                    else:
                        # Projected CRS (meters)
                        gsd_cm = pixel_size * 100
                        print(f"📊 GSD 추출: {gsd_cm:.2f} cm/pixel")
                else:
                    print("⚠ geoTransform pixel_size가 0 → GSD 추출 불가")

        # Setup directories
        base_dir = project_root_dir(project_id)
        output_dir = base_dir / "exports"
        work_dir = processing_work_dir(project_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        target_ortho_crs = settings.AUTO_EXPORT_TARGET_CRS or "EPSG:5186"
        if str(target_ortho_crs).strip().isdigit():
            target_ortho_crs = f"EPSG:{str(target_ortho_crs).strip()}"
        base_cog_object_name = orthomosaic_key(
            project_id,
            str(target_ortho_crs),
            region=project.region,
            title=project.title,
        )
        storage = get_storage()
        publishing_id = str(self.request.id or project_id).replace("/", "_")
        final_cog_path = output_dir / (
            f".{Path(base_cog_object_name).stem}.{publishing_id}.publishing.tif"
        )

        # 소스가 이미 최종 경로에 있으면 복사/이동 불필요
        source_is_final = source.resolve() == final_cog_path.resolve()

        # Check if input is already COG
        is_cog = False
        try:
            metadata = gdalinfo_data.get('metadata', {})
            image_structure = metadata.get('IMAGE_STRUCTURE', {})
            if image_structure.get('LAYOUT') == 'COG':
                is_cog = True
        except Exception:
            pass

        if source_is_final:
            if is_cog:
                print("✓ 입력 파일이 이미 최종 경로에 COG 형식으로 존재")
            else:
                print("🔄 COG 형식으로 변환 중...")
                temp_cog = output_dir / "_result_cog_converting.tif"
                try:
                    _convert_to_cog(str(source), str(temp_cog))
                    shutil.move(str(temp_cog), str(final_cog_path))
                    print("✓ COG 변환 완료")
                except Exception as e:
                    temp_cog.unlink(missing_ok=True)
                    return {"status": "error", "message": f"COG 변환 실패: {e}"}
        elif is_cog:
            print("✓ 입력 파일이 이미 COG 형식, 이동 중...")
            shutil.move(str(source), str(final_cog_path))
        else:
            print("🔄 COG 형식으로 변환 중...")
            try:
                _convert_to_cog(str(source), str(final_cog_path))
                print("✓ COG 변환 완료")
                source.unlink(missing_ok=True)
            except Exception as e:
                return {"status": "error", "message": f"COG 변환 실패: {e}"}

        # Ensure the stored orthomosaic is a COG in the configured target CRS.
        if _is_cog_in_target_crs(final_cog_path, str(target_ortho_crs)):
            print(f"✓ 입력 파일이 이미 대상 CRS({target_ortho_crs})의 COG 형식")
        else:
            warped_cog_path = output_dir / f".{publishing_id}.warped.tif"
            try:
                _warp_to_cog(str(final_cog_path), str(warped_cog_path), str(target_ortho_crs))
                shutil.move(str(warped_cog_path), str(final_cog_path))
            except Exception as e:
                warped_cog_path.unlink(missing_ok=True)
                return {"status": "error", "message": f"정사영상 COG/CRS 변환 실패: {e}"}

        # Upload / move to storage
        cog_object_name = _select_orthomosaic_target(
            db,
            project,
            base_cog_object_name,
            storage,
        )
        if cog_object_name != base_cog_object_name:
            print(
                "정사영상 파일명 중복을 피해 저장합니다: "
                f"{Path(cog_object_name).name}"
            )
        print("📤 스토리지로 이동/업로드 중...")
        final_cog_path = _upload_cog_to_storage(final_cog_path, cog_object_name, storage)
        print(f"✓ 스토리지 저장 완료: {final_cog_path}")

        # File size (체크섬은 대용량 파일에서 수십 분 소요되므로 건너뜀)
        file_size = os.path.getsize(str(final_cog_path))
        checksum = None

        # Extract bounds from the final COG
        bounds_wkt = get_orthophoto_bounds(str(final_cog_path))

        # Find or create ProcessingJob
        job = db.query(ProcessingJob).filter(
            ProcessingJob.project_id == project_id
        ).order_by(ProcessingJob.started_at.desc()).first()

        if not job:
            job = ProcessingJob(
                project_id=project_id,
                engine="external",
                started_at=datetime.utcnow(),
            )
            db.add(job)
            db.flush()

        # Update ProcessingJob
        job.status = "completed"
        job.completed_at = datetime.utcnow()
        job.result_gsd = gsd_cm
        job.result_path = cog_object_name
        job.result_checksum = checksum
        job.result_size = file_size
        job.progress = 100
        job.error_message = None
        job.error_code = None
        job.error_reference = None
        if not job.started_at:
            job.started_at = datetime.utcnow()

        # Update Project
        project.status = "completed"
        project.progress = 100
        project.ortho_path = cog_object_name
        project.ortho_size = file_size

        if bounds_wkt:
            _update_project_geo(project, bounds_wkt, db)

        db.commit()

        # Clean up: 소스가 최종 경로와 다르고 아직 남아있으면 삭제
        if not source_is_final and source.exists():
            try:
                source.unlink()
                print(f"✓ 원본 파일 삭제: {source}")
            except Exception:
                pass

        # Write status.json
        status_data = {
            "status": "completed",
            "progress": 100,
            "message": "외부 COG 삽입 완료",
            "result_gsd": gsd_cm,
            "updated_at": datetime.utcnow().isoformat()
        }
        status_path = work_dir / "status.json"
        with open(status_path, "w", encoding="utf-8") as f:
            json.dump(status_data, f, ensure_ascii=False, indent=2)

        # Broadcast via WebSocket
        _broadcast_ws(project_id, "completed", 100, "외부 COG 삽입 완료")

        gsd_str = f"{gsd_cm:.2f} cm/pixel" if gsd_cm else "N/A"
        size_mb = file_size / (1024 * 1024)
        print(f"✅ 프로젝트 {project_id} COG 삽입 완료")
        print(f"   GSD: {gsd_str}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Checksum: {checksum[:16] + '...' if checksum else 'N/A'}")
        print(f"   Region: {project.region}")

        return {
            "status": "completed",
            "project_id": project_id,
            "result_path": cog_object_name,
            "gsd_cm": gsd_cm,
            "checksum": checksum,
            "size": file_size,
        }
