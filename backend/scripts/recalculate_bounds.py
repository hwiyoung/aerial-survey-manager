import asyncio
import os
import sys
import tempfile
import subprocess
import json
from pathlib import Path
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# Add app to path
sys.path.append(os.path.join(os.path.dirname(__file__), ".."))

from app.database import async_session
from app.models.project import Project
from app.services.storage import get_storage
from app.config import get_settings

settings = get_settings()

def get_orthophoto_bounds(file_path: str):
    """Extract WGS84 bounding box from orthophoto using gdalinfo."""
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
