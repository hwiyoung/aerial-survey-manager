"""
Seed camera models from io.csv file.
This script parses the io.csv file and inserts camera models into the database.
"""
import os
import asyncio
import sys
import re
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, text

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models.project import CameraModel

settings = get_settings()
SQLALCHEMY_DATABASE_URL = settings.DATABASE_URL


def parse_io_csv(file_path: str) -> List[Dict[str, Any]]:
    """Parse io.csv file and extract camera models."""
    cameras = []
    current_camera = None

    # Read with multiple encodings to handle Korean text
    content = None
    for encoding in ['utf-8', 'cp949', 'euc-kr', 'utf-8-sig']:
        try:
            with open(file_path, 'r', encoding=encoding) as f:
                content = f.read()
            break
        except UnicodeDecodeError:
            continue

    if content is None:
        raise ValueError(f"Could not read file with any known encoding: {file_path}")

    lines = content.split('\n')

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Parse CSV fields
        parts = [p.strip() for p in line.split(',')]

        if parts[0] == '$CAMERA':
            current_camera = {}
        elif parts[0] == '$END_CAMERA':
            if current_camera and 'name' in current_camera:
                cameras.append(current_camera)
            current_camera = None
        elif current_camera is not None:
            # Check for field definitions
            if len(parts) > 1:
                field = parts[0] if parts[0] else (parts[1] if len(parts) > 1 else '')

                if '$CAMERA_NAME:' in field or (len(parts) > 1 and '$CAMERA_NAME:' in parts[1]):
                    # Camera name is after $CAMERA_NAME:
                    idx = 2 if '$CAMERA_NAME:' in parts[1] else 1
                    if len(parts) > idx:
                        current_camera['name'] = parts[idx]

                elif '$LENS_SN:' in field or (len(parts) > 1 and '$LENS_SN:' in parts[1]):
                    # Company names (can be multiple)
                    idx = 2 if '$LENS_SN:' in parts[1] else 1
                    companies = []
                    for i in range(idx, min(idx + 3, len(parts))):
                        if parts[i] and not parts[i].startswith('$'):
                            companies.append(parts[i])
                    if companies:
                        current_camera['companies'] = companies

                elif '$FOCAL_LENGTH:' in field or (len(parts) > 1 and '$FOCAL_LENGTH:' in parts[1]):
                    idx = 2 if '$FOCAL_LENGTH:' in parts[1] else 1
                    if len(parts) > idx and parts[idx]:
                        try:
                            current_camera['focal_length'] = float(parts[idx])
                        except ValueError:
                            pass

                elif '$SENSOR_SIZE:' in field or (len(parts) > 1 and '$SENSOR_SIZE:' in parts[1]):
                    idx = 2 if '$SENSOR_SIZE:' in parts[1] else 1
                    if len(parts) > idx + 1:
                        try:
                            current_camera['sensor_width_px'] = int(parts[idx])
                            current_camera['sensor_height_px'] = int(parts[idx + 1])
                        except ValueError:
                            pass

                elif '$PIXEL_SIZE:' in field or (len(parts) > 1 and '$PIXEL_SIZE:' in parts[1]):
                    idx = 2 if '$PIXEL_SIZE:' in parts[1] else 1
                    if len(parts) > idx:
                        try:
                            current_camera['pixel_size'] = float(parts[idx])
                        except ValueError:
                            pass

                elif '$PRINCIPAL_POINT_AUTOCOLLIMATION:' in field or (len(parts) > 1 and '$PRINCIPAL_POINT_AUTOCOLLIMATION:' in parts[1]):
                    idx = 2 if '$PRINCIPAL_POINT_AUTOCOLLIMATION:' in parts[1] else 1
                    if len(parts) > idx + 1:
                        try:
                            current_camera['ppa_x'] = float(parts[idx])
                            current_camera['ppa_y'] = float(parts[idx + 1])
                        except ValueError:
                            pass

    return cameras


def calculate_sensor_dimensions(camera: Dict[str, Any]) -> Dict[str, Any]:
    """Calculate sensor dimensions in mm from pixel size."""
    result = camera.copy()

    pixel_size = camera.get('pixel_size', 0)  # µm
    sensor_width_px = camera.get('sensor_width_px', 0)
    sensor_height_px = camera.get('sensor_height_px', 0)

    if pixel_size and sensor_width_px:
        # Convert: mm = pixels * µm / 1000
        result['sensor_width'] = round(sensor_width_px * pixel_size / 1000, 2)

    if pixel_size and sensor_height_px:
        result['sensor_height'] = round(sensor_height_px * pixel_size / 1000, 2)

    return result


def create_camera_entries(cameras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create unique camera entries by $CAMERA_NAME only (no company suffix)."""
    entries = []
    seen_names = set()

    for camera in cameras:
        camera = calculate_sensor_dimensions(camera)
        name = camera.get('name', '')

        if not name:
            continue

        # Only add unique camera names (skip duplicates)
        if name not in seen_names:
            seen_names.add(name)
            entries.append({
                'name': name,
                'focal_length': camera.get('focal_length'),
                'sensor_width': camera.get('sensor_width'),
                'sensor_height': camera.get('sensor_height'),
                'pixel_size': camera.get('pixel_size'),
                'sensor_width_px': camera.get('sensor_width_px'),
                'sensor_height_px': camera.get('sensor_height_px'),
                'ppa_x': camera.get('ppa_x'),
                'ppa_y': camera.get('ppa_y'),
                'is_custom': False
            })

    return entries


async def seed_camera_models(file_path: str, clear_existing: bool = False, sync_mode: bool = False):
    """Seed camera models from io.csv file.

    Args:
        file_path: Path to io.csv file
        clear_existing: Delete ALL camera models before seeding
        sync_mode: Delete cameras not in io.csv and update existing ones
    """
    engine = create_async_engine(SQLALCHEMY_DATABASE_URL)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    # Ensure tables exist
    async with engine.begin() as conn:
        from app.database import Base
        import app.models  # noqa
        await conn.run_sync(Base.metadata.create_all)

    print(f"Parsing io.csv from {file_path}...")
    cameras = parse_io_csv(file_path)
    print(f"Found {len(cameras)} camera definitions.")

    entries = create_camera_entries(cameras)
    print(f"Created {len(entries)} camera model entries.")

    # Create name -> entry mapping for updates
    entry_by_name = {e['name']: e for e in entries}
    valid_names = set(entry_by_name.keys())

    async with async_session() as session:
        if clear_existing:
            # Delete ALL camera models (both custom and standard)
            await session.execute(text("DELETE FROM camera_models"))
            print("Cleared ALL existing camera models.")
        elif sync_mode:
            # Delete cameras not in io.csv (only non-custom ones)
            result = await session.execute(
                select(CameraModel).where(CameraModel.is_custom == False)
            )
            existing_cameras = result.scalars().all()

            deleted = 0
            for cam in existing_cameras:
                if cam.name not in valid_names:
                    await session.delete(cam)
                    deleted += 1
                    print(f"  Deleted: {cam.name}")

            if deleted > 0:
                await session.commit()
                print(f"Deleted {deleted} camera models not in io.csv.")

        # Get existing cameras for update/insert
        result = await session.execute(select(CameraModel))
        existing_cameras = {cam.name: cam for cam in result.scalars().all()}

        inserted = 0
        updated = 0
        skipped = 0

        for entry in entries:
            if entry['name'] in existing_cameras:
                if sync_mode:
                    # Update existing camera with new data
                    cam = existing_cameras[entry['name']]
                    cam.focal_length = entry['focal_length']
                    cam.sensor_width = entry['sensor_width']
                    cam.sensor_height = entry['sensor_height']
                    cam.pixel_size = entry['pixel_size']
                    cam.sensor_width_px = entry.get('sensor_width_px')
                    cam.sensor_height_px = entry.get('sensor_height_px')
                    cam.ppa_x = entry.get('ppa_x')
                    cam.ppa_y = entry.get('ppa_y')
                    updated += 1
                else:
                    skipped += 1
                continue

            camera_model = CameraModel(
                name=entry['name'],
                focal_length=entry['focal_length'],
                sensor_width=entry['sensor_width'],
                sensor_height=entry['sensor_height'],
                pixel_size=entry['pixel_size'],
                sensor_width_px=entry.get('sensor_width_px'),
                sensor_height_px=entry.get('sensor_height_px'),
                ppa_x=entry.get('ppa_x'),
                ppa_y=entry.get('ppa_y'),
                is_custom=entry['is_custom'],
                organization_id=None
            )
            session.add(camera_model)
            inserted += 1

            if inserted % 10 == 0:
                await session.commit()
                print(f"Inserted {inserted} camera models...")

        await session.commit()
        print(f"\nSeed complete: {inserted} inserted, {updated} updated, {skipped} skipped")


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='Seed camera models from io.csv')
    parser.add_argument('--file', '-f', default='/app/data/io.csv',
                        help='Path to io.csv file')
    parser.add_argument('--clear', '-c', action='store_true',
                        help='Clear ALL camera models before seeding')
    parser.add_argument('--sync', '-s', action='store_true',
                        help='Sync mode: delete cameras not in io.csv and update existing ones')
    args = parser.parse_args()

    file_path = args.file

    # Also check relative path from script location
    if not os.path.exists(file_path):
        alt_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 'data', 'io.csv')
        if os.path.exists(alt_path):
            file_path = alt_path

    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        print("Please provide a valid path to io.csv using --file option")
        sys.exit(1)

    asyncio.run(seed_camera_models(file_path, clear_existing=args.clear, sync_mode=args.sync))
