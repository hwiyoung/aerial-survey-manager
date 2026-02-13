import asyncio
import os
import sys
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add app to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models.project import Project, Image, ProcessingJob
from app.services.storage import get_storage
from app.config import get_settings

settings = get_settings()

async def sync_data():
    print("Starting data synchronization...")
    storage = get_storage()
    
    async with async_session() as db:
        # 1. Fetch all projects
        result = await db.execute(select(Project))
        projects = result.scalars().all()
        
        for project in projects:
            print(f"Checking project: {project.title} ({project.id})")
            
            # If ortho_path is missing, try to find it from business logic or jobs
            if not project.ortho_path:
                print(f"  [-] ortho_path is NULL. Checking processing jobs...")
                job_result = await db.execute(
                    select(ProcessingJob)
                    .where(ProcessingJob.project_id == project.id, ProcessingJob.status == 'completed')
                    .order_by(ProcessingJob.completed_at.desc())
                )
                job = job_result.scalar_one_or_none()
                if job and job.result_path:
                    print(f"  [+] Found result_path in job: {job.result_path}. Updating project.")
                    project.ortho_path = job.result_path
                else:
                    # Try default path in MinIO
                    default_path = f"projects/{project.id}/ortho/result_cog.tif"
                    if storage.object_exists(default_path):
                        print(f"  [+] Found COG in MinIO at default path. Updating project.")
                        project.ortho_path = default_path
            
            # Final verification of ortho_path
            if project.ortho_path:
                exists_in_minio = storage.object_exists(project.ortho_path)
                if not exists_in_minio:
                    print(f"  [!] Orthophoto still missing in MinIO: {project.ortho_path}")
                    # Check local storage as fallback
                    local_path = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project.id) / "output" / "result_cog.tif"
                    if not local_path.exists():
                         local_path = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project.id) / "orthophoto.tif"
                    
                    if local_path.exists():
                        print(f"  [+] Found locally at {local_path}. Re-uploading...")
                        storage.upload_file(str(local_path), project.ortho_path, "image/tiff")
                        print("  [+] Re-upload complete.")
                    else:
                        print("  [-] Not found locally. Clearing ortho_path in DB.")
                        project.ortho_path = None
                else:
                    print(f"  [OK] Orthophoto exists in MinIO.")
            
            # 2. Check Images
            img_result = await db.execute(select(Image).where(Image.project_id == project.id))
            images = img_result.scalars().all()
            for img in images:
                # If original_path is NULL, try to recover it
                if not img.original_path:
                    # Default path used by tus-webhook: projects/{project_id}/images/{image_name}
                    # Actually, some might be hashed or stored differently. 
                    # Let's try to find an object that matches the filename.
                    print(f"    [-] original_path is NULL for {img.filename}. Skipping auto-recovery for now.")
                
                if img.original_path:
                    if not storage.object_exists(img.original_path):
                        print(f"    [!] Image missing: {img.filename} ({img.original_path})")
                        img.upload_status = 'error'
        
        await db.commit()
    print("Synchronization finished.")

if __name__ == "__main__":
    asyncio.run(sync_data())
