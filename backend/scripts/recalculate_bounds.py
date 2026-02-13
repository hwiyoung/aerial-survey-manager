import asyncio
import os
import sys
import tempfile
from sqlalchemy import select

# Add app to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models.project import Project
from app.services.storage import get_storage
from app.config import get_settings
from app.utils.gdal import extract_bounds_wkt as get_orthophoto_bounds

settings = get_settings()

async def recalculate_all_bounds():
    storage = get_storage()
    
    async with async_session() as db:
        result = await db.execute(select(Project).where(Project.ortho_path != None))
        projects = result.scalars().all()
        print(f"Found {len(projects)} projects with ortho_path.")
        
        for project in projects:
            print(f"Processing project: {project.title} ({project.id})")
            
            with tempfile.NamedTemporaryFile(suffix=".tif") as tmp:
                try:
                    # Download from MinIO
                    print(f"  Downloading {project.ortho_path}...")
                    storage.download_file(project.ortho_path, tmp.name)
                    
                    # Extract bounds
                    print(f"  Extracting bounds...")
                    bounds_wkt = get_orthophoto_bounds(tmp.name)
                    if bounds_wkt:
                        print(f"  [+] New bounds: {bounds_wkt}")
                        project.bounds = bounds_wkt
                        await db.commit()
                        print(f"  [+] Updated DB.")
                    else:
                        print(f"  [-] Could not extract bounds.")
                except Exception as e:
                    print(f"  [!] Error: {e}")

if __name__ == "__main__":
    asyncio.run(recalculate_all_bounds())
