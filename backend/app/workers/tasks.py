"""Celery application and async tasks."""
import os
import hashlib
from datetime import datetime
from pathlib import Path

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
        "app.workers.tasks.process_orthophoto_odm": {"queue": "odm"},
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
                """Update progress in database and Celery state."""
                job.progress = progress
                project.progress = progress
                db.commit()
                self.update_state(
                    state="PROGRESS",
                    meta={"progress": progress, "message": message}
                )
            
            update_progress(5, "Downloading images from storage...")
            
            for i, image in enumerate(images):
                if image.original_path:
                    local_path = input_dir / image.filename
                    storage.download_file(image.original_path, str(local_path))
                    
                    # Update download progress
                    download_progress = 5 + int((i + 1) / len(images) * 15)
                    update_progress(download_progress, f"Downloaded {i + 1}/{len(images)} images")
            
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
            
            # Calculate checksum
            update_progress(95, "Calculating checksum...")
            checksum = calculate_file_checksum(str(result_path))
            file_size = os.path.getsize(result_path)
            
            # Update job with result
            job.status = "completed"
            job.progress = 100
            job.completed_at = datetime.utcnow()
            job.result_path = str(result_path)  # Local path for direct download
            job.result_checksum = checksum
            job.result_size = file_size
            
            project.status = "completed"
            project.progress = 100
            
            db.commit()
            
            return {
                "status": "completed",
                "result_path": str(result_path),
                "checksum": checksum,
                "size": file_size,
            }
            
        except Exception as e:
            # Handle error
            job.status = "error"
            job.error_message = str(e)
            project.status = "error"
            db.commit()
            
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
