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
from app.models.project import Project, Image
from app.config import get_settings
from app.services.storage import StorageService

settings = get_settings()


async def cleanup_local_processing():
    """Clean up orphaned local processing folders."""
    print("\n=== Cleaning up local processing folders ===")

    # 1. Get all project IDs from DB
    async with async_session() as db:
        result = await db.execute(select(Project.id))
        active_project_ids = {str(project_id) for project_id in result.scalars().all()}

    print(f"Found {len(active_project_ids)} active projects in DB.")

    # 2. List folders in processing directory
    processing_dir = Path(settings.LOCAL_DATA_PATH) / "processing"
    if not processing_dir.exists():
        print(f"Directory {processing_dir} does not exist. Skipping.")
        return 0

    deleted_count = 0
    for item in processing_dir.iterdir():
        if item.is_dir():
            folder_name = item.name

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

    print(f"Local cleanup finished. Deleted {deleted_count} folders.")
    return deleted_count


async def cleanup_minio_uploads(dry_run: bool = True):
    """Clean up orphaned uploads in MinIO storage.

    Args:
        dry_run: If True, only report what would be deleted without actually deleting.
    """
    print("\n=== Cleaning up MinIO uploads ===")
    if dry_run:
        print("(DRY RUN - no files will be deleted)")

    storage = StorageService()

    # 1. Get all original_paths from DB
    async with async_session() as db:
        result = await db.execute(
            select(Image.original_path).where(Image.original_path.isnot(None))
        )
        db_paths = {row[0] for row in result.fetchall()}

    print(f"Found {len(db_paths)} image paths in DB.")

    # 2. List all objects in uploads/ prefix
    try:
        upload_objects = storage.list_objects(prefix="uploads/", recursive=True)
    except Exception as e:
        print(f"Failed to list MinIO objects: {e}")
        return 0

    print(f"Found {len(upload_objects)} objects in MinIO uploads/")

    # 3. Find orphaned objects (in MinIO but not in DB)
    # Extract base paths (without trailing parts like /part.1, etc.)
    orphaned_bases = set()
    for obj_path in upload_objects:
        # uploads/abc123def456 or uploads/abc123def456/part.1
        parts = obj_path.split('/')
        if len(parts) >= 2:
            base_path = '/'.join(parts[:2])  # uploads/{hash}
            # Check if this base is referenced in DB
            if base_path not in db_paths:
                orphaned_bases.add(base_path)

    print(f"Found {len(orphaned_bases)} orphaned upload bases.")

    if not orphaned_bases:
        print("No orphaned uploads to clean.")
        return 0

    # 4. Delete orphaned objects
    deleted_count = 0
    total_size = 0

    for base_path in sorted(orphaned_bases):
        # Get all objects under this base
        related_objects = [obj for obj in upload_objects if obj.startswith(base_path)]

        # Calculate size
        size_bytes = 0
        for obj in related_objects:
            try:
                size_bytes += storage.get_object_size(obj)
            except Exception:
                pass

        size_mb = size_bytes / (1024 * 1024)
        total_size += size_bytes

        if dry_run:
            print(f"  [DRY] Would delete: {base_path} ({len(related_objects)} objects, {size_mb:.1f} MB)")
        else:
            print(f"  [!] Deleting: {base_path} ({len(related_objects)} objects, {size_mb:.1f} MB)")
            try:
                storage.delete_recursive(f"{base_path}/")
                # Also try direct object deletion
                try:
                    storage.delete_object(base_path)
                except Exception:
                    pass
                # Delete .info file/folder
                storage.delete_recursive(f"{base_path}.info/")
                try:
                    storage.delete_object(f"{base_path}.info")
                except Exception:
                    pass
                deleted_count += 1
                print(f"  [+] Deleted {base_path}")
            except Exception as e:
                print(f"  [x] Failed to delete {base_path}: {e}")

    total_size_gb = total_size / (1024 * 1024 * 1024)
    if dry_run:
        print(f"\nDry run finished. Would delete {len(orphaned_bases)} upload groups ({total_size_gb:.2f} GB).")
        print("Run with --execute to actually delete these files.")
    else:
        print(f"\nMinIO cleanup finished. Deleted {deleted_count} upload groups ({total_size_gb:.2f} GB).")

    return deleted_count


async def cleanup_orphaned_data(include_minio: bool = False, dry_run: bool = True):
    """Main cleanup function.

    Args:
        include_minio: If True, also clean up MinIO uploads.
        dry_run: If True for MinIO, only report what would be deleted.
    """
    print("Starting cleanup of orphaned data...")

    # Clean local processing folders
    local_deleted = await cleanup_local_processing()

    # Clean MinIO uploads if requested
    minio_deleted = 0
    if include_minio:
        minio_deleted = await cleanup_minio_uploads(dry_run=dry_run)

    print(f"\n=== Summary ===")
    print(f"Local folders deleted: {local_deleted}")
    if include_minio:
        print(f"MinIO uploads {'would be ' if dry_run else ''}deleted: {minio_deleted}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Clean up orphaned data")
    parser.add_argument(
        "--minio",
        action="store_true",
        help="Also clean up orphaned MinIO uploads"
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually delete MinIO files (default is dry-run)"
    )

    args = parser.parse_args()

    asyncio.run(cleanup_orphaned_data(
        include_minio=args.minio,
        dry_run=not args.execute
    ))
