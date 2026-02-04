import os
import json
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine
from app.config import get_settings
from app.models.region import Region

settings = get_settings()
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL

async def import_regions(file_path):
    # Use async engine
    engine = create_async_engine(SQLALCHEMY_DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Create table if it doesn't exist
    async with engine.begin() as conn:
        from app.database import Base
        # We need to import all models that use Base to ensure they are registered
        import app.models # noqa
        await conn.run_sync(Base.metadata.create_all)

    print(f"Reading GeoJSON from {file_path}...")
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    features = data.get('features', [])
    print(f"Found {len(features)} features.")

    async with async_session() as session:
        # Create table if it doesn't exist (optional, usually handled by migrations)
        # For now, assume it exists or we can create it
        # await session.execute(text("CREATE EXTENSION IF NOT EXISTS postgis"))
        
        # Clear existing regions (user said to use this file as source)
        # await session.execute(text("DELETE FROM regions"))
        
        count = 0
        for feature in features:
            props = feature.get('properties', {})
            geom_data = feature.get('geometry')
            
            if not geom_data:
                continue
                
            layer = props.get('layer', 'Unknown')
            name = props.get('MAPIDCD_NO', '')
            
            # Convert geometry to WKT or use ST_GeomFromGeoJSON
            # Since GeoAlchemy2 supports WKT easier in some versions:
            geom_json_str = json.dumps(geom_data)
            
            # We use ST_GeomFromGeoJSON and ensure it's MultiPolygon in EPSG:5179
            # The MultiPolygon type in our model expects MultiPolygon
            
            # PostGIS ST_GeomFromGeoJSON defaults to 4326 if not specified, 
            # but we know it's 5179.
            
            # Using raw SQL for geometry insertion is safer with GeoJSON
            from sqlalchemy import insert
            
            stmt = text("""
                INSERT INTO regions (id, name, layer, geom)
                VALUES (gen_random_uuid(), :name, :layer, ST_Multi(ST_SetSRID(ST_GeomFromGeoJSON(:geom_json), 5179)))
            """)
            
            await session.execute(stmt, {
                "name": str(name),
                "layer": layer,
                "geom_json": geom_json_str
            })
            
            count += 1
            if count % 100 == 0:
                print(f"Imported {count} regions...")
                await session.commit()

        await session.commit()
        print(f"Successfully imported {count} regions.")

if __name__ == "__main__":
    # 명령줄 인자가 있으면 사용, 없으면 기본 경로들에서 탐색
    if len(sys.argv) > 1:
        file_path = sys.argv[1]
    else:
        # 가능한 경로들을 순서대로 탐색
        possible_paths = [
            "/app/data/전국_권역_5K_5179.geojson",
            "/app/data/regions.geojson",
            "data/전국_권역_5K_5179.geojson",
            "data/regions.geojson",
        ]
        file_path = None
        for path in possible_paths:
            if os.path.exists(path):
                file_path = path
                break

        if not file_path:
            print("No GeoJSON file found in default paths.")
            print(f"Searched: {possible_paths}")
            sys.exit(0)  # 파일이 없어도 에러가 아님

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        sys.exit(1)

    asyncio.run(import_regions(file_path))
