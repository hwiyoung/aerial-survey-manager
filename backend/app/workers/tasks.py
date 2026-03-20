"""Celery application and async tasks."""
import os
import json
import time
from datetime import datetime
from datetime import timedelta
from pathlib import Path
from typing import Optional, List
try:
    import resource
except Exception:
    resource = None

from celery import Celery

from app.config import get_settings
from app.auth.jwt import create_internal_token
from app.utils.checksum import calculate_file_checksum
from app.utils.formatting import format_elapsed as _fmt_elapsed
from app.utils.gdal import extract_bounds_wkt as get_orthophoto_bounds

settings = get_settings()

QUEUE_WAIT_WARN_SECONDS = float(os.getenv("PROCESSING_QUEUE_WAIT_WARN_SECONDS", "300"))
PROCESSING_TOTAL_WARN_SECONDS = float(os.getenv("PROCESSING_TOTAL_WARN_SECONDS", "7200"))
PROCESSING_MEMORY_WARN_MB = float(os.getenv("PROCESSING_MEMORY_WARN_MB", "8192"))
ENABLE_EXTERNAL_COG_INGEST = (
    os.getenv("ENABLE_EXTERNAL_COG_INGEST", "false").strip().lower() == "true"
)

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
    # 기본 visibility_timeout(1시간)이 만료되면 Redis가 task를 재전달함.
    # 2000장 처리 시 24시간+, 여러 프로젝트 대기 시 합산 대기시간을 고려해 7일로 설정.
    broker_transport_options={"visibility_timeout": 604800},
    # prefetch=1: worker가 queue에서 1개 task만 가져옴.
    # prefetch>1이면 대기 task들도 Redis에서 in-flight로 카운트되어 visibility_timeout 소비.
    worker_prefetch_multiplier=1,
    task_routes={
        "app.workers.tasks.process_orthophoto": {"queue": "metashape"},
        # 썸네일 태스크는 전용 워커에서 처리 (처리 중에도 동시 실행)
        "app.workers.tasks.generate_thumbnail": {"queue": "thumbnail"},
        "app.workers.tasks.regenerate_missing_thumbnails": {"queue": "thumbnail"},
        "app.workers.tasks.delete_project_data": {"queue": "celery"},
        "app.workers.tasks.save_eo_metadata": {"queue": "celery"},
        "app.workers.tasks.delete_source_images": {"queue": "celery"},
        "app.workers.tasks.inject_external_cog": {"queue": "celery"},
    },
)


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

def _broadcast_ws(project_id: str, status: str, progress: int, message: str):
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
                "message": message
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
            # or a storage object key (e.g. "images/{project_id}/file.jpg")
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



# ============================================================================
# Main processing task
# ============================================================================

@celery_app.task(bind=True, name="app.workers.tasks.process_orthophoto", acks_late=True)
def process_orthophoto(self, job_id: str, project_id: str, options: dict):
    """
    Main orthophoto processing task.
    
    Dispatches to configured processing engines (metashape/odm/external).
    """
    import asyncio
    from app.models.project import Project, ProcessingJob, Image
    from app.services.processing_router import processing_router
    from app.services.storage import get_storage
    from app.utils.db import sync_db_session

    with sync_db_session() as db:
        # Get job and project
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        project = db.query(Project).filter(Project.id == project_id).first()

        if not job or not project:
            return {"status": "error", "message": "Job or project not found"}

        # 멱등성 체크: 이미 완료된 job이면 재실행하지 않음
        # (Redis visibility_timeout 만료로 인한 재전달 방어)
        if job.status == "completed":
            print(f"[process_orthophoto] Job {job_id} already completed, skipping re-execution.")
            return {"status": "skipped", "message": "Job already completed"}

        try:
            queue_name = "unknown"
            try:
                queue_name = self.request.delivery_info.get("routing_key", "unknown")
            except Exception:
                pass

            # Update status to processing
            job.status = "processing"
            job.started_at = datetime.utcnow()
            project.status = "processing"
            db.commit()

            queue_wait_seconds = None
            queued_at = getattr(job, 'queued_at', None) or getattr(job, 'created_at', None)
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
            base_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project_id)
            input_dir = base_dir / "images"
            output_dir = base_dir / ".work"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Download images from storage
            storage = get_storage()
            images = db.query(Image).filter(
                Image.project_id == project_id,
                Image.upload_status == "completed",
            ).all()
            
            status_file = base_dir / "processing_status.json"

            def write_status_file(
                progress: int,
                message: str,
                status_value: str = "processing",
                metrics: dict[str, object] | None = None,
            ):
                try:
                    payload = {
                        "status": status_value,
                        "progress": progress,
                        "message": message,
                        "updated_at": datetime.utcnow().isoformat(),
                    }
                    if metrics is not None:
                        payload["metrics"] = metrics
                    with open(status_file, "w", encoding="utf-8") as f:
                        json.dump(payload, f)
                except Exception:
                    pass

            def update_progress(progress, message=""):
                """Update progress in database, Celery state, and broadcast via WebSocket."""
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
            print(f"[Processing] Engine dispatch: {engine_name} / queue={queue_name}")
            
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
                        options=options,
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
            result_object_name = f"projects/{project_id}/ortho/result_cog.tif"

            try:
                import shutil

                # 엔진(Metashape 등)이 이미 COG를 생성한 경우 변환 스킵
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

                update_progress(92, "결과물 저장 중...")

                result_path = _upload_cog_to_storage(cog_path, result_object_name, storage)
                if not is_local_storage:
                    # MinIO: COG를 output/으로 이동 (체크섬/bounds 추출용)
                    final_output_dir = base_dir / "output"
                    final_output_dir.mkdir(parents=True, exist_ok=True)
                    final_cog_path = final_output_dir / "result_cog.tif"
                    shutil.move(str(cog_path), str(final_cog_path))
                    result_path = final_cog_path

                # Clean up intermediate files in .work/ (숨김 폴더)
                update_progress(93, "중간 파일 정리 중...")
                files_to_keep = {"status.json", ".processing.log"}

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
                result_object_name = f"projects/{project_id}/ortho/result.tif"
                storage.upload_file(str(result_path), result_object_name, "image/tiff")
            phase_timings.append(("COG/저장/정리", time.time() - t0))

            # Phase 4: 체크섬 계산 + 영역 정보 추출
            t0 = time.time()
            update_progress(95, "체크섬 계산 중...")
            checksum = calculate_file_checksum(str(result_path))
            file_size = os.path.getsize(result_path)

            update_progress(96, "프로젝트 영역 정보 추출 중...")
            bounds_wkt = get_orthophoto_bounds(str(result_path))

            # MinIO 모드에서만 로컬 COG 삭제 (로컬 모드에서는 스토리지 자체가 로컬)
            if not is_local_storage and result_path.exists():
                try:
                    result_path.unlink()
                    output_parent = result_path.parent
                    if output_parent.exists() and not any(output_parent.iterdir()):
                        output_parent.rmdir()
                    print(f"Deleted local COG after upload: {result_path}")
                except Exception as del_err:
                    print(f"Failed to delete local COG: {del_err}")

            phase_timings.append(("체크섬/영역추출", time.time() - t0))

            # Phase 5: 영역 정보 업데이트
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
            log_file_path = output_dir / ".processing.log"
            try:
                with open(log_file_path, 'a') as log_f:
                    log_f.write(f"\n{summary_text}\n")
            except Exception:
                pass

            # Final status update
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            project.status = "completed"
            project.progress = 100
            project.ortho_path = result_object_name  # Store ortho path in project
            project.ortho_size = file_size
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
            
        except Exception as e:
            # Handle error - extract user-friendly message from processing output
            error_str = str(e)
            
            # Try to find [ERROR] message in output
            user_friendly_error = "처리 중 오류가 발생했습니다."
            if "[ERROR]" in error_str:
                # Extract the ERROR line
                import re
                error_match = re.search(r'\[ERROR\]\s*(.+?)(?:\n|$)', error_str)
                if error_match:
                    user_friendly_error = error_match.group(1).strip()
            elif "Exit code:" in error_str:
                user_friendly_error = "처리 실패 (데이터 품질 문제일 수 있음)"
            
            job.status = "error"
            job.error_message = user_friendly_error
            project.status = "error"
            project.error_message = user_friendly_error  # Also save to project for UI display
            db.commit()
            try:
                error_metrics = {"error_message": user_friendly_error}
                if 'phase_timings' in dir():
                    error_metrics["phase_elapsed_seconds"] = {
                        pn: round(el, 2) for pn, el in phase_timings
                    }
                write_status_file(0, user_friendly_error, status_value="error", metrics=error_metrics)
            except NameError:
                pass  # write_status_file/phase_timings not yet defined (early failure)
            
            # Broadcast error via WebSocket
            _broadcast_ws(project_id, "error", 0, user_friendly_error)

            raise


def _generate_thumbnail_gdal(source_path: str, dest_path: str, size: int = 256):
    """gdal_translate로 썸네일 생성 (오버뷰 활용 시 빠름).

    gdalinfo로 밴드 수/데이터 타입을 먼저 확인해 gdal_translate를 한 번만 실행.
    - 8-bit: -scale 생략 (파일을 한 번만 읽음)
    - 16-bit 이상: -scale 추가 (0-255 변환 필요)
    - 밴드 4개 이상: -b 1 -b 2 -b 3 으로 RGB만 추출
    """
    import subprocess, json

    # 파일 메타데이터 확인 (픽셀 데이터 미읽음, 빠름)
    info = subprocess.run(
        ["gdalinfo", "-json", source_path],
        capture_output=True, text=True, timeout=30
    )
    if info.returncode != 0:
        raise RuntimeError(f"gdalinfo 실패: {info.stderr.strip()}")

    meta = json.loads(info.stdout)
    bands = meta.get("bands", [])
    band_count = len(bands)
    data_type = bands[0].get("type", "Byte") if bands else "Byte"

    cmd = ["gdal_translate", "-of", "JPEG", "-outsize", str(size), "0", "-r", "average"]

    # 4밴드 이상(RGBN 등)이면 첫 3밴드만 선택
    if band_count > 3:
        cmd += ["-b", "1", "-b", "2", "-b", "3"]

    # 16-bit 이상이면 0-255 스케일링 필요 (8-bit는 생략해 파일을 한 번만 읽음)
    if data_type not in ("Byte",):
        cmd += ["-scale"]

    cmd += [source_path, dest_path]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if result.returncode != 0:
        raise RuntimeError(f"gdal_translate 실패: {result.stderr.strip()}")


def _generate_thumbnail_pil(source_path: str, dest_path: str, size: int = 256):
    """PIL로 썸네일 생성 (폴백, 전체 파일 읽음)."""
    from PIL import Image as PILImage
    PILImage.MAX_IMAGE_PIXELS = 300000000
    with PILImage.open(source_path) as img:
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img.thumbnail((size, size))
        img.save(dest_path, "JPEG", quality=85)


@celery_app.task(
    bind=True,
    name="app.workers.tasks.generate_thumbnail",
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

            thumb_object_name = f"projects/{image.project_id}/thumbnails/{image.filename}.jpg"
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
)
def delete_project_data(self, project_id: str):
    """프로젝트의 로컬 처리 데이터를 삭제합니다."""
    import shutil

    local_path = Path(settings.LOCAL_DATA_PATH) / "processing" / project_id

    if local_path.exists():
        try:
            shutil.rmtree(local_path)
            print(f"✓ 프로젝트 데이터 삭제 완료: {local_path}")
            return {"status": "deleted", "path": str(local_path)}
        except Exception as e:
            print(f"✗ 프로젝트 데이터 삭제 실패 {local_path}: {e}")
            return {"status": "error", "path": str(local_path), "error": str(e)}
    else:
        print(f"ℹ 삭제할 데이터 없음: {local_path}")
        return {"status": "not_found", "path": str(local_path)}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.save_eo_metadata",
)
def save_eo_metadata(self, project_id: str, reference_crs: str, reference_rows: list):
    """EO 메타데이터를 로컬 파일로 저장합니다.

    Args:
        project_id: 프로젝트 UUID
        reference_crs: 좌표계 (예: "EPSG:5186")
        reference_rows: [(name, x, y, z, omega, phi, kappa), ...] 형식의 데이터
    """
    reference_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / project_id / "images"
    reference_dir.mkdir(parents=True, exist_ok=True)
    reference_path = reference_dir / "metadata.txt"

    try:
        with open(reference_path, "w", encoding="utf-8") as f:
            if reference_crs:
                f.write(f"# CRS {reference_crs}\n")
            for row in reference_rows:
                name, x_val, y_val, z_val, omega, phi, kappa = row
                f.write(f"{name} {x_val} {y_val} {z_val} {omega} {phi} {kappa}\n")

        print(f"✓ EO 메타데이터 저장 완료: {reference_path} ({len(reference_rows)}개 항목)")
        return {"status": "saved", "path": str(reference_path), "count": len(reference_rows)}
    except Exception as e:
        print(f"✗ EO 메타데이터 저장 실패: {e}")
        return {"status": "error", "path": str(reference_path), "error": str(e)}


@celery_app.task(
    bind=True,
    name="app.workers.tasks.delete_source_images",
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
            # 원본 이미지 삭제 (images/{project_id}/)
            images_prefix = f"images/{project_id}/"
            objects = storage.list_objects(prefix=images_prefix, recursive=True)
            if objects:
                storage.delete_recursive(images_prefix)
                deleted_count = len(objects)
                print(f"✓ 원본 이미지 삭제: {deleted_count}개 ({images_prefix})")
            else:
                print(f"ℹ 원본 이미지 없음: {images_prefix}")

            # 썸네일도 삭제
            thumbnails_prefix = f"projects/{project_id}/thumbnails/"
            thumb_objects = storage.list_objects(prefix=thumbnails_prefix, recursive=True)
            if thumb_objects:
                storage.delete_recursive(thumbnails_prefix)
                print(f"✓ 썸네일 삭제: {len(thumb_objects)}개")

            freed_bytes = project.source_size or 0
            freed_gb = freed_bytes / (1024 * 1024 * 1024)
            print(f"✅ 프로젝트 {project_id} 원본 이미지 삭제 완료 ({freed_gb:.2f} GB 확보)")

            return {
                "status": "completed",
                "project_id": project_id,
                "deleted_count": deleted_count,
                "freed_bytes": freed_bytes,
            }

        except Exception as e:
            # Revert source_deleted flag on failure (API set it optimistically)
            project.source_deleted = False
            db.commit()
            print(f"✗ 원본 이미지 삭제 실패 (source_deleted 복원): {e}")
            return {"status": "error", "message": str(e)}


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
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return {"status": "error", "message": f"프로젝트를 찾을 수 없습니다: {project_id}"}

        # Check for running processing jobs
        running_job = db.query(ProcessingJob).filter(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status.in_(["queued", "processing"])
        ).first()

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
        base_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / project_id
        output_dir = base_dir / "output"
        work_dir = base_dir / ".work"
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        final_cog_path = output_dir / "result_cog.tif"

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

        # Upload / move to storage
        storage = get_storage()
        cog_object_name = f"projects/{project_id}/ortho/result_cog.tif"

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
        job.result_path = str(final_cog_path)
        job.result_checksum = checksum
        job.result_size = file_size
        job.progress = 100
        job.error_message = None
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
