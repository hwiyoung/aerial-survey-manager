"""Celery application and async tasks."""
import os
import hashlib
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
    from app.utils.geo import extract_center_from_wkt, get_region_for_point
    
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
            base_dir = Path(f"/data/processing/{project_id}")
            input_dir = base_dir / "images"
            output_dir = base_dir / "output"
            input_dir.mkdir(parents=True, exist_ok=True)
            output_dir.mkdir(parents=True, exist_ok=True)
            
            # Download images from storage
            storage = StorageService()
            images = db.query(Image).filter(
                Image.project_id == project_id,
                Image.upload_status == "completed",
            ).all()
            
            def update_progress(progress, message=""):
                """Update progress in database, Celery state, and broadcast via WebSocket."""
                job.progress = progress
                project.progress = progress
                db.commit()
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
            
            update_progress(5, "Downloading images from storage...")
            
            total_source_size = 0
            for i, image in enumerate(images):
                if image.file_size:
                    total_source_size += image.file_size
                
                if image.original_path:
                    local_path = input_dir / image.filename
                    storage.download_file(image.original_path, str(local_path))
                    
                    # Update download progress
                    download_progress = 5 + int((i + 1) / len(images) * 15)
                    update_progress(download_progress, f"Downloaded {i + 1}/{len(images)} images")
            
            project.source_size = total_source_size
            db.commit()
            
            update_progress(20, "Starting processing engine...")
            
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
            
            update_progress(90, "Uploading result to storage...")
            
            # Upload result to storage
            result_object_name = f"projects/{project_id}/ortho/result.tif"
            storage.upload_file(str(result_path), result_object_name, "image/tiff")
            
            # Convert to COG (Cloud Optimized GeoTIFF) for efficient streaming
            update_progress(92, "Converting to Cloud Optimized GeoTIFF (COG)...")
            cog_path = output_dir / "result_cog.tif"
            
            try:
                import subprocess
                # Use GDAL to create COG with proper tiling and overviews
                gdal_cmd = [
                    "gdal_translate",
                    "-of", "COG",
                    "-co", "COMPRESS=LZW",
                    "-co", "TILING_SCHEME=GoogleMapsCompatible",
                    "-co", "OVERVIEW_RESAMPLING=AVERAGE",
                    str(result_path),
                    str(cog_path)
                ]
                subprocess.run(gdal_cmd, check=True, capture_output=True)
                
                # Upload COG version
                cog_object_name = f"projects/{project_id}/ortho/result_cog.tif"
                storage.upload_file(str(cog_path), cog_object_name, "image/tiff")
                
                # Use COG as primary result
                result_path = cog_path
                result_object_name = cog_object_name
            except Exception as cog_error:
                # COG conversion failed, continue with regular TIF
                print(f"COG conversion failed: {cog_error}")
            
            # Calculate checksum
            update_progress(95, "Calculating checksum...")
            checksum = calculate_file_checksum(str(result_path))
            file_size = os.path.getsize(result_path)
            
            # Update project bounds from orthophoto
            update_progress(98, "Updating project footprint...")
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
                        region = get_region_for_point(lon, lat)
                        if region:
                            project.region = region
            
            # Final status update
            project.status = "completed"
            project.progress = 100
            project.ortho_path = result_object_name  # Store ortho path in project
            project.ortho_size = file_size
            db.commit()

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


@celery_app.task(bind=True, name="app.workers.tasks.generate_thumbnail")
def generate_thumbnail(self, image_id: str):
    """Generate thumbnail for an uploaded image."""
    from PIL import Image as PILImage
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.models.project import Image
    from app.services.storage import StorageService
    
    sync_db_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_db_url)
    
    with Session(engine) as db:
        image = db.query(Image).filter(Image.id == image_id).first()
        if not image or not image.original_path:
            return {"status": "error", "message": "Image not found"}
        
        storage = StorageService()
        
        # Download original
        temp_path = f"/tmp/{image.filename}"
        storage.download_file(image.original_path, temp_path)
        
        # Generate thumbnail
        try:
            with PILImage.open(temp_path) as img:
                img.thumbnail((256, 256))
                thumb_path = f"/tmp/thumb_{image.filename}"
                img.save(thumb_path, "JPEG", quality=85)
            
            # Upload thumbnail
            thumb_object_name = f"projects/{image.project_id}/thumbnails/{image.filename}.jpg"
            storage.upload_file(thumb_path, thumb_object_name, "image/jpeg")
            
            # Update database
            image.thumbnail_path = thumb_object_name
            db.commit()
            
            # Cleanup
            os.remove(temp_path)
            os.remove(thumb_path)
            
            return {"status": "completed", "thumbnail_path": thumb_object_name}
            
        except Exception as e:
            return {"status": "error", "message": str(e)}
