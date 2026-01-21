import asyncio
import os
import sys
import shutil
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add app to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models.project import Project
from app.config import get_settings

settings = get_settings()

async def cleanup_orphaned_data():
    print("Starting cleanup of orphaned data folders...")
    
    # 1. Get all project IDs from DB
    async with async_session() as db:
        result = await db.execute(select(Project.id))
        active_project_ids = {str(project_id) for project_id in result.scalars().all()}
    
    print(f"Found {len(active_project_ids)} active projects in DB.")
    
    # 2. List folders in processing directory
    processing_dir = Path(settings.LOCAL_DATA_PATH) / "processing"
    if not processing_dir.exists():
        print(f"Directory {processing_dir} does not exist. Skipping.")
        return
    
    deleted_count = 0
    for item in processing_dir.iterdir():
        if item.is_dir():
            folder_name = item.name
            
            # Skip non-UUID like manual folders if they don't look like UUIDs
            # but usually they are project IDs.
            # We skip some known manual folders if necessary, but here we'll check if it's NOT in active_project_ids
            if folder_name not in active_project_ids:
                # Extra check: is it a UUID?
                is_uuid = False
                if len(folder_name) == 36 and folder_name.count('-') == 4:
                    is_uuid = True
                
                # Manual folders like 'jongman', 'proj1', 'test_cog'
                manual_folders = {'jongman', 'proj1', 'proj2', 'test_cog'}
                
                if is_uuid or folder_name in manual_folders:
                    print(f"  [!] Found orphan folder: {folder_name}. Deleting...")
                    try:
                        shutil.rmtree(item)
                        deleted_count += 1
                        print(f"  [+] Deleted {folder_name}")
                    except Exception as e:
                        print(f"  [x] Failed to delete {folder_name}: {e}")
                else:
                    print(f"  [?] Skipping untracked non-UUID folder: {folder_name}")

    print(f"Cleanup finished. Deleted {deleted_count} folders.")

if __name__ == "__main__":
    asyncio.run(cleanup_orphaned_data())
