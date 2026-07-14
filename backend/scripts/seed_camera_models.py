"""
Seed camera models from io.csv file.
This script parses the io.csv file and inserts camera models into the database.
"""
import os
import asyncio
import sys
import csv
from typing import List, Dict, Any

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import func, select, text

# Add parent directory to path to import app modules
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config import get_settings
from app.models.project import CameraModel, Image

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

    for row in csv.reader(content.splitlines()):
        parts = [p.strip() for p in row]
        if not parts or not any(parts):
            continue

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
                    for value in parts[idx:]:
                        if not value or value.startswith('$'):
                            break
                        companies.append(value)
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
    """Calculate sensor dimensions in mm from io.csv pixel size.

    io.csv stores $PIXEL_SIZE in micrometers. The database keeps that raw
    value for display/selection, while processing converts it to millimeters
    immediately before forwarding IO to Metashape.
    """
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


def _company_values(camera: Dict[str, Any]) -> List[str]:
    return [
        str(company).strip()
        for company in camera.get('companies', [])
        if str(company).strip()
    ]


def _company_label(camera: Dict[str, Any]) -> str:
    return ", ".join(_company_values(camera))


def _camera_display_name(base_name: str, company_label: str, used_names: set[str]) -> str:
    display_name = f"{base_name} - {company_label}" if company_label else base_name

    if display_name not in used_names:
        return display_name

    suffix = 2
    while f"{display_name} #{suffix}" in used_names:
        suffix += 1
    return f"{display_name} #{suffix}"


def _legacy_names(base_name: str, companies: List[str]) -> List[str]:
    legacy_names = [base_name]
    if companies:
        legacy_names.append(f"{base_name} - {', '.join(companies)}")
    if len(companies) > 3:
        legacy_names.append(f"{base_name} - {', '.join(companies[:3])}")
    return legacy_names


def create_camera_entries(cameras: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Create one camera entry per company shown in each io.csv camera block."""
    entries = []
    seen_names = set()

    for camera in cameras:
        camera = calculate_sensor_dimensions(camera)
        base_name = camera.get('name', '').strip()

        if not base_name:
            continue

        companies = _company_values(camera)
        company_labels = companies or ['']
        legacy_names = _legacy_names(base_name, companies)

        for company_label in company_labels:
            name = _camera_display_name(base_name, company_label, seen_names)
            seen_names.add(name)
            entries.append({
                'name': name,
                'base_name': base_name,
                'company_label': company_label,
                'legacy_names': legacy_names,
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


def _apply_camera_entry(camera_model: CameraModel, entry: Dict[str, Any]) -> None:
    camera_model.name = entry['name']
    camera_model.focal_length = entry['focal_length']
    camera_model.sensor_width = entry['sensor_width']
    camera_model.sensor_height = entry['sensor_height']
    camera_model.pixel_size = entry['pixel_size']
    camera_model.sensor_width_px = entry.get('sensor_width_px')
    camera_model.sensor_height_px = entry.get('sensor_height_px')
    camera_model.ppa_x = entry.get('ppa_x')
    camera_model.ppa_y = entry.get('ppa_y')


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
    first_entry_by_legacy_name: dict[str, Dict[str, Any]] = {}
    for entry in entries:
        for legacy_name in entry.get('legacy_names', []):
            first_entry_by_legacy_name.setdefault(legacy_name, entry)

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
            migrated = 0
            reserved_names = {cam.name for cam in existing_cameras}
            for cam in existing_cameras:
                if cam.name not in valid_names:
                    first_entry = first_entry_by_legacy_name.get(cam.name)
                    if first_entry and first_entry['name'] not in reserved_names:
                        old_name = cam.name
                        _apply_camera_entry(cam, first_entry)
                        reserved_names.discard(old_name)
                        reserved_names.add(first_entry['name'])
                        migrated += 1
                        print(f"  Migrated: {old_name} -> {first_entry['name']}")
                        continue
                    referenced_count = await session.scalar(
                        select(func.count(Image.id)).where(Image.camera_model_id == cam.id)
                    )
                    if referenced_count:
                        print(
                            f"  Kept referenced camera model not in io.csv: "
                            f"{cam.name} ({referenced_count} image references)"
                        )
                        continue
                    await session.delete(cam)
                    deleted += 1
                    print(f"  Deleted: {cam.name}")

            if deleted > 0 or migrated > 0:
                await session.commit()
                print(f"Migrated {migrated} legacy camera models.")
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
                    cam = existing_cameras[entry['name']]
                    if cam.is_custom:
                        skipped += 1
                    else:
                        # Keep packaged io.csv changes synced for untouched standard models.
                        _apply_camera_entry(cam, entry)
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
