"""Celery application and async tasks."""
import os
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from celery import Celery

from app.config import get_settings

settings = get_settings()

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
    task_routes={
        "app.workers.tasks.process_orthophoto": {"queue": "odm"},  # default to odm
        "app.workers.tasks.process_orthophoto_metashape": {"queue": "metashape"},
        "app.workers.tasks.process_orthophoto_external": {"queue": "external"},
        # 썸네일은 처리 엔진과 분리 - 별도 celery 워커에서 처리
        "app.workers.tasks.generate_thumbnail": {"queue": "celery"},
        "app.workers.tasks.regenerate_missing_thumbnails": {"queue": "celery"},
        # 프로젝트 데이터 삭제는 worker-engine에서 처리 (root 권한 필요)
        "app.workers.tasks.delete_project_data": {"queue": "metashape"},
        # EO 메타데이터 저장 (root 권한 필요)
        "app.workers.tasks.save_eo_metadata": {"queue": "metashape"},
        # 외부 COG 삽입 (root + GDAL + MinIO 접근 필요)
        "app.workers.tasks.inject_external_cog": {"queue": "metashape"},
    },
)


def calculate_file_checksum(file_path: str) -> str:
    """Calculate SHA256 checksum of a file."""
    hash_sha256 = hashlib.sha256()
    with open(file_path, 'rb') as f:
        while chunk := f.read(1024 * 1024):
            hash_sha256.update(chunk)
    return hash_sha256.hexdigest()


def get_orthophoto_bounds(file_path: str) -> Optional[str]:
    """Extract WGS84 bounding box from orthophoto using gdalinfo."""
    import subprocess
    import json
    try:
        cmd = ["gdalinfo", "-json", file_path]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        data = json.loads(result.stdout)
        
        # Look for wgs84Extent (Polygon)
        extent = data.get("wgs84Extent")
        if extent and extent.get("type") == "Polygon":
            coords = extent.get("coordinates", [[]])[0]
            if len(coords) >= 4:
                # Convert to WKT Polygon: POLYGON((lon1 lat1, lon2 lat2, ...))
                wkt_points = [f"{pt[0]} {pt[1]}" for pt in coords]
                # Ensure it's closed
                if wkt_points[0] != wkt_points[-1]:
                    wkt_points.append(wkt_points[0])
                return f"SRID=4326;POLYGON(({', '.join(wkt_points)}))"
    except Exception as e:
        print(f"Failed to extract bounds from {file_path}: {e}")
    return None


def calculate_area_km2(wkt_polygon: str) -> float:
    """Calculate area of a WKT polygon in km2 using PostGIS geometry."""
    # This will be done via SQL query in the task
    return 0.0


def get_best_region_overlap(wkt_polygon: str, db_session) -> Optional[str]:
    """Find the region that has the most overlapping area with the given polygon."""
    from sqlalchemy import text
    try:
        # Query regions table to find the layer with maximum intersection area
        query = text("""
            SELECT layer
            FROM regions
            WHERE ST_Intersects(geom, ST_Transform(ST_GeomFromText(:wkt, 4326), 5179))
            ORDER BY ST_Area(ST_Intersection(geom, ST_Transform(ST_GeomFromText(:wkt, 4326), 5179))) DESC
            LIMIT 1
        """)
        result = db_session.execute(query, {"wkt": wkt_polygon}).fetchone()
        if result:
            return result[0]
    except Exception as e:
        print(f"Failed to find best region: {e}")
    return None


@celery_app.task(bind=True, name="app.workers.tasks.process_orthophoto")
def process_orthophoto(self, job_id: str, project_id: str, options: dict):
    """
    Main orthophoto processing task.
    
    Routes to appropriate engine based on options.
    """
    import asyncio
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.project import Project, ProcessingJob, Image
    from app.services.processing_router import processing_router
    from app.services.storage import StorageService
    from app.utils.geo import extract_center_from_wkt, get_region_for_point_sync
    
    # Use sync database connection for Celery
    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_db_url)
    
    with Session(engine) as db:
        # Get job and project
        job = db.query(ProcessingJob).filter(ProcessingJob.id == job_id).first()
        project = db.query(Project).filter(Project.id == project_id).first()
        
        if not job or not project:
            return {"status": "error", "message": "Job or project not found"}
        
        try:
            # Update status to processing
            job.status = "processing"
            job.started_at = datetime.utcnow()
            project.status = "processing"
            db.commit()
            
            # Setup directories
            base_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project_id)
            input_dir = base_dir / "images"
            output_dir = base_dir / ".work"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Download images from storage
            storage = StorageService()
            images = db.query(Image).filter(
                Image.project_id == project_id,
                Image.upload_status == "completed",
            ).all()
            
            status_file = base_dir / "processing_status.json"

            def write_status_file(progress, message, status_value="processing"):
                try:
                    payload = {
                        "status": status_value,
                        "progress": progress,
                        "message": message,
                        "updated_at": datetime.utcnow().isoformat()
                    }
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
                # Broadcast to WebSocket clients
                try:
                    import httpx
                    httpx.post(
                        "http://api:8000/api/v1/processing/broadcast",
                        json={
                            "project_id": project_id,
                            "status": "processing",
                            "progress": progress,
                            "message": message
                        },
                        timeout=2.0
                    )
                except Exception:
                    pass  # Don't fail the task if broadcast fails
            
            update_progress(5, "저장소에서 이미지 다운로드 중...")

            total_source_size = 0
            for i, image in enumerate(images):
                if image.file_size:
                    total_source_size += image.file_size

                if image.original_path:
                    local_path = input_dir / image.filename
                    storage.download_file(image.original_path, str(local_path))

                    # Update download progress
                    download_progress = 5 + int((i + 1) / len(images) * 15)
                    update_progress(download_progress, f"{i + 1}/{len(images)} 이미지 다운로드 완료")

            project.source_size = total_source_size
            db.commit()

            update_progress(20, "처리 엔진 시작 중...")
            
            # Define async progress callback
            async def progress_callback(progress, message):
                # Celery tasks are sync, so we just update directly
                scaled_progress = 20 + int(progress * 0.7)  # Scale to 20-90%
                update_progress(scaled_progress, message)
            
            # Run processing engine
            engine_name = options.get("engine", "odm")
            
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

            # Read result_gsd from status.json (Metashape engine)
            if engine_name == "metashape":
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

            update_progress(90, "결과물 업로드 중...")
            
            # Upload result to storage
            result_object_name = f"projects/{project_id}/ortho/result.tif"
            storage.upload_file(str(result_path), result_object_name, "image/tiff")
            
            # Convert to COG (Cloud Optimized GeoTIFF) for efficient streaming
            update_progress(92, "클라우드 최적화 GeoTIFF 변환 중...")
            cog_path = output_dir / "result_cog.tif"
            
            try:
                import subprocess
                import shutil

                # 엔진(Metashape 등)이 이미 COG를 생성한 경우 변환 스킵
                if cog_path.exists():
                    print(f"COG already created by engine, skipping conversion: {cog_path}")
                else:
                    # Use GDAL to create COG with proper tiling and overviews
                    # Note: TILING_SCHEME 제거하여 원본 GSD 유지
                    gdal_cmd = [
                        "gdal_translate",
                        "-of", "COG",
                        "-co", "COMPRESS=LZW",
                        "-co", "BLOCKSIZE=256",
                        "-co", "OVERVIEW_RESAMPLING=AVERAGE",
                        "-co", "BIGTIFF=YES",
                        str(result_path),
                        str(cog_path)
                    ]
                    subprocess.run(gdal_cmd, check=True, capture_output=True)

                # Upload COG version
                cog_object_name = f"projects/{project_id}/ortho/result_cog.tif"
                storage.upload_file(str(cog_path), cog_object_name, "image/tiff")

                # result_cog.tif를 output/ 디렉토리로 이동 (고객에게 보이는 결과물)
                final_output_dir = base_dir / "output"
                final_output_dir.mkdir(parents=True, exist_ok=True)
                final_cog_path = final_output_dir / "result_cog.tif"
                shutil.move(str(cog_path), str(final_cog_path))

                # Use COG as primary result
                result_path = final_cog_path
                result_object_name = cog_object_name

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

                # Clean input directory (downloaded images)
                if input_dir.exists():
                    try:
                        shutil.rmtree(input_dir)
                        print(f"Cleaned up input directory: {input_dir}")
                    except Exception as cleanup_err:
                        print(f"Failed to clean up input directory: {cleanup_err}")

            except Exception as cog_error:
                # COG conversion failed, continue with regular TIF
                print(f"COG conversion failed: {cog_error}")
            
            # Calculate checksum
            update_progress(95, "체크섬 계산 중...")
            checksum = calculate_file_checksum(str(result_path))
            file_size = os.path.getsize(result_path)
            
            # Update project bounds from orthophoto
            update_progress(98, "프로젝트 영역 정보 업데이트 중...")
            bounds_wkt = get_orthophoto_bounds(str(result_path))
            if bounds_wkt:
                project.bounds = bounds_wkt
                
                # Calculate area using PostGIS
                try:
                    from sqlalchemy import text
                    # Project to 5179 (suitable for Korea area calculation)
                    area_query = text("SELECT ST_Area(ST_Transform(ST_GeomFromText(:wkt, 4326), 5179)) / 1000000.0")
                    area_result = db.execute(area_query, {"wkt": bounds_wkt}).scalar()
                    project.area = area_result
                except Exception as area_err:
                    print(f"Area calculation failed: {area_err}")
                
                # Auto-assign region based on overlap
                best_region = get_best_region_overlap(bounds_wkt, db)
                if best_region:
                    project.region = best_region
                elif not project.region:
                    # Fallback to point check if no intersection found in regions table
                    lon, lat = extract_center_from_wkt(bounds_wkt)
                    if lon and lat:
                        region = get_region_for_point_sync(db, lon, lat)
                        if region:
                            project.region = region
            
            # Final status update
            job.status = "completed"
            job.completed_at = datetime.utcnow()
            project.status = "completed"
            project.progress = 100
            project.ortho_path = result_object_name  # Store ortho path in project
            project.ortho_size = file_size
            db.commit()
            write_status_file(100, "Processing completed successfully", status_value="completed")

            # Broadcast completion via WebSocket AFTER all DB updates
            try:
                import httpx
                # Call internal API to broadcast WebSocket update
                httpx.post(
                    f"http://api:8000/api/v1/processing/broadcast",
                    json={
                        "project_id": project_id,
                        "status": "completed",
                        "progress": 100,
                        "message": "Processing completed successfully"
                    },
                    timeout=5.0
                )
            except Exception as ws_error:
                print(f"WebSocket broadcast failed: {ws_error}")
            
            return {
                "status": "completed",
                "result_path": result_object_name,
                "checksum": checksum,
                "size": file_size,
            }
            
        except Exception as e:
            # Handle error - extract user-friendly message from ODM output
            error_str = str(e)
            
            # Try to find [ERROR] message in ODM output
            user_friendly_error = "처리 중 오류가 발생했습니다."
            if "[ERROR]" in error_str:
                # Extract the ERROR line
                import re
                error_match = re.search(r'\[ERROR\]\s*(.+?)(?:\n|$)', error_str)
                if error_match:
                    user_friendly_error = error_match.group(1).strip()
            elif "Exit code:" in error_str:
                user_friendly_error = "ODM 처리 실패 (데이터 품질 문제일 수 있음)"
            
            job.status = "error"
            job.error_message = user_friendly_error
            project.status = "error"
            project.error_message = user_friendly_error  # Also save to project for UI display
            db.commit()
            write_status_file(0, user_friendly_error, status_value="error")
            
            # Broadcast error via WebSocket
            try:
                httpx.post(
                    f"http://api:8000/api/v1/processing/broadcast",
                    json={
                        "project_id": project_id,
                        "status": "error",
                        "progress": 0,
                        "message": user_friendly_error
                    },
                    timeout=5.0
                )
            except Exception:
                pass
            
            raise


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
    from PIL import Image as PILImage
    # Increase limit for large aerial images (e.g., UltraCam Eagle: 17310x11310 = 195MP)
    PILImage.MAX_IMAGE_PIXELS = 300000000  # 300 megapixels
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.project import Image
    from app.services.storage import StorageService

    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_db_url)

    temp_path = None
    thumb_path = None

    with Session(engine) as db:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image or not image.original_path:
            return {"status": "error", "message": "Image not found or no original path"}

        # Skip if thumbnail already exists (unless force=True)
        if image.thumbnail_path and not force:
            return {"status": "skipped", "message": "Thumbnail already exists"}

        storage = StorageService()

        # Download original
        temp_path = f"/tmp/{image_id}_{image.filename}"
        try:
            storage.download_file(image.original_path, temp_path)
        except Exception as e:
            print(f"Failed to download original image {image_id}: {e}")
            raise  # Will trigger retry

        # Generate thumbnail
        try:
            with PILImage.open(temp_path) as img:
                # Handle RGBA images (convert to RGB for JPEG)
                if img.mode in ('RGBA', 'LA', 'P'):
                    img = img.convert('RGB')
                img.thumbnail((256, 256))
                thumb_path = f"/tmp/thumb_{image_id}_{image.filename}.jpg"
                img.save(thumb_path, "JPEG", quality=85)

            # Upload thumbnail
            thumb_object_name = f"projects/{image.project_id}/thumbnails/{image.filename}.jpg"
            storage.upload_file(thumb_path, thumb_object_name, "image/jpeg")

            # Update database
            image.thumbnail_path = thumb_object_name
            db.commit()

            return {"status": "completed", "thumbnail_path": thumb_object_name}

        except Exception as e:
            print(f"Thumbnail generation failed for {image_id}: {e}")
            raise  # Will trigger retry

        finally:
            # Cleanup temp files
            if temp_path and os.path.exists(temp_path):
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
    from sqlalchemy import create_engine, and_
    from sqlalchemy.orm import Session
    from app.models.project import Image

    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_db_url)

    with Session(engine) as db:
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
    """
    프로젝트의 로컬 처리 데이터를 삭제합니다.
    worker-engine에서 root 권한으로 실행됩니다.
    """
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
    """
    EO 메타데이터를 로컬 파일로 저장합니다.
    worker-engine에서 root 권한으로 실행됩니다.

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
    name="app.workers.tasks.inject_external_cog",
)
def inject_external_cog(self, project_id: str, source_path: str, gsd_cm: float = None, force: bool = False):
    """
    외부에서 생성한 COG/GeoTIFF를 프로젝트에 삽입하여 완료 상태로 만듭니다.
    worker-engine에서 root 권한으로 실행됩니다.

    Args:
        project_id: 프로젝트 UUID
        source_path: COG/GeoTIFF 파일 경로 (컨테이너 내부 경로)
        gsd_cm: GSD (cm/pixel), None이면 자동 추출
        force: True면 처리 중인 태스크를 강제 취소
    """
    import subprocess
    import shutil
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import Session
    from app.models.project import Project, ProcessingJob
    from app.services.storage import StorageService
    from app.utils.geo import extract_center_from_wkt, get_region_for_point_sync

    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    db_engine = create_engine(sync_db_url)

    source = Path(source_path)
    if not source.exists():
        return {"status": "error", "message": f"파일을 찾을 수 없습니다: {source_path}"}

    with Session(db_engine) as db:
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
                capture_output=True, text=True, check=True
            )
            gdalinfo_data = json.loads(gdalinfo_result.stdout)
        except subprocess.CalledProcessError as e:
            return {"status": "error", "message": f"유효한 GeoTIFF가 아닙니다: {e.stderr}"}
        except Exception as e:
            return {"status": "error", "message": f"gdalinfo 실행 실패: {e}"}

        # Extract GSD if not provided
        if gsd_cm is None:
            geo_transform = gdalinfo_data.get('geoTransform', [])
            if len(geo_transform) >= 2:
                pixel_size = abs(geo_transform[1])
                coord_wkt = gdalinfo_data.get('coordinateSystem', {}).get('wkt', '')
                if 'GEOGCS' in coord_wkt and 'PROJCS' not in coord_wkt:
                    # Geographic CRS (degrees) - 한국 위도 기준 근사 변환
                    gsd_cm = pixel_size * 111320 * 0.8 * 100
                    print(f"⚠ Geographic CRS 감지, GSD 근사값: {gsd_cm:.2f} cm/pixel (정확한 값은 --gsd 옵션 사용)")
                else:
                    # Projected CRS (meters)
                    gsd_cm = pixel_size * 100
                    print(f"📊 GSD 추출: {gsd_cm:.2f} cm/pixel")

        # Setup directories
        base_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / project_id
        output_dir = base_dir / "output"
        work_dir = base_dir / ".work"
        output_dir.mkdir(parents=True, exist_ok=True)
        work_dir.mkdir(parents=True, exist_ok=True)

        final_cog_path = output_dir / "result_cog.tif"

        # Check if input is already COG
        is_cog = False
        try:
            metadata = gdalinfo_data.get('metadata', {})
            image_structure = metadata.get('IMAGE_STRUCTURE', {})
            if image_structure.get('LAYOUT') == 'COG':
                is_cog = True
        except Exception:
            pass

        if is_cog:
            print("✓ 입력 파일이 이미 COG 형식, 복사 중...")
            shutil.copy2(str(source), str(final_cog_path))
        else:
            print("🔄 COG 형식으로 변환 중...")
            try:
                gdal_cmd = [
                    "gdal_translate", "-of", "COG",
                    "-co", "COMPRESS=LZW",
                    "-co", "BLOCKSIZE=256",
                    "-co", "OVERVIEW_RESAMPLING=AVERAGE",
                    "-co", "BIGTIFF=YES",
                    str(source), str(final_cog_path)
                ]
                subprocess.run(gdal_cmd, check=True, capture_output=True)
                print("✓ COG 변환 완료")
            except subprocess.CalledProcessError as e:
                return {"status": "error", "message": f"COG 변환 실패: {e.stderr}"}

        # Upload to MinIO
        print("📤 MinIO 업로드 중...")
        storage = StorageService()
        cog_object_name = f"projects/{project_id}/ortho/result_cog.tif"
        storage.upload_file(str(final_cog_path), cog_object_name, "image/tiff")
        print(f"✓ MinIO 업로드 완료: {cog_object_name}")

        # Calculate checksum and file size
        checksum = calculate_file_checksum(str(final_cog_path))
        file_size = os.path.getsize(str(final_cog_path))

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
            project.bounds = bounds_wkt

            # Calculate area using PostGIS
            try:
                area_query = text(
                    "SELECT ST_Area(ST_Transform(ST_GeomFromEWKT(:wkt), 5179)) / 1000000.0"
                )
                area_result = db.execute(area_query, {"wkt": bounds_wkt}).scalar()
                project.area = area_result
            except Exception as area_err:
                print(f"⚠ 면적 계산 실패: {area_err}")

            # Auto-assign region
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

        db.commit()

        # Clean up staging file (only if it's our temporary copy)
        if source.name == "_inject_cog.tif":
            try:
                source.unlink()
                print(f"✓ 스테이징 파일 삭제: {source}")
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
        try:
            import httpx
            httpx.post(
                "http://api:8000/api/v1/processing/broadcast",
                json={
                    "project_id": project_id,
                    "status": "completed",
                    "progress": 100,
                    "message": "외부 COG 삽입 완료"
                },
                timeout=5.0
            )
        except Exception:
            pass

        gsd_str = f"{gsd_cm:.2f} cm/pixel" if gsd_cm else "N/A"
        size_mb = file_size / (1024 * 1024)
        print(f"✅ 프로젝트 {project_id} COG 삽입 완료")
        print(f"   GSD: {gsd_str}")
        print(f"   Size: {size_mb:.1f} MB")
        print(f"   Checksum: {checksum[:16]}...")
        print(f"   Region: {project.region}")

        return {
            "status": "completed",
            "project_id": project_id,
            "result_path": cog_object_name,
            "gsd_cm": gsd_cm,
            "checksum": checksum,
            "size": file_size,
        }
