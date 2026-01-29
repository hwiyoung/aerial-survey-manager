import asyncio
import os
import sys
from uuid import UUID

# Add parent directory to path for imports
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.database import async_session
from app.models.project import Image
from sqlalchemy import select
from app.workers.tasks import generate_thumbnail

async def backfill_thumbnails():
    async with async_session() as db:
        result = await db.execute(
            select(Image).where(
                Image.original_path.isnot(None),
                Image.thumbnail_path.is_(None)
            )
        )
        images = result.scalars().all()
        print(f"Found {len(images)} images needing thumbnails.")
        
        for img in images:
            print(f"Triggering thumbnail for {img.filename} ({img.id})")
            generate_thumbnail.delay(str(img.id))
            
    print("Done triggering thumbnail tasks.")

if __name__ == "__main__":
    asyncio.run(backfill_thumbnails())
