"""Verified cleanup for data that belongs to a deleted project."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from uuid import UUID

from app.config import get_settings
from app.services.storage import get_storage
from app.utils.storage_paths import (
    orthomosaic_project_prefix,
    project_root_dir,
)


def _delete_prefix_verified(storage, prefix: str) -> int:
    before = storage.list_objects(prefix=prefix, recursive=True)
    storage.delete_recursive(prefix)
    remaining = storage.list_objects(prefix=prefix, recursive=True)
    if remaining:
        raise RuntimeError(
            f"Storage cleanup incomplete for {prefix}: {len(remaining)} objects remain"
        )
    return len(before)


def cleanup_project_storage(
    project_id: str | UUID,
    original_paths: list[str],
    ortho_path: str | None = None,
) -> int:
    """Delete project-owned storage objects and verify no prefix remains."""
    storage = get_storage()
    deleted_count = 0

    for raw_path in original_paths:
        path = str(raw_path or "")
        if not path or os.path.isabs(path):
            continue
        for object_name in (path, f"{path}.info"):
            deleted_count += _delete_prefix_verified(storage, f"{object_name}/")
            if storage.object_exists(object_name):
                storage.delete_object(object_name)
            if storage.object_exists(object_name):
                raise RuntimeError(f"Storage object cleanup incomplete: {object_name}")

    if ortho_path:
        if os.path.isabs(ortho_path):
            settings = get_settings()
            resolved = Path(ortho_path).resolve()
            allowed_roots = {
                Path(settings.EXPORT_ROOT_PATH).resolve(),
                Path(settings.LOCAL_STORAGE_PATH).resolve(),
            }
            if any(resolved.is_relative_to(root) for root in allowed_roots):
                resolved.unlink(missing_ok=True)
        elif storage.object_exists(ortho_path):
            storage.delete_object(ortho_path)

    deleted_count += _delete_prefix_verified(
        storage,
        orthomosaic_project_prefix(project_id),
    )
    deleted_count += _delete_prefix_verified(storage, f"projects/{project_id}/")
    return deleted_count


def cleanup_project_data(
    project_id: str | UUID,
    original_paths: list[str],
    ortho_path: str | None = None,
) -> dict:
    """Delete object storage and local processing data for one project."""
    deleted_objects = cleanup_project_storage(project_id, original_paths, ortho_path)

    local_path = project_root_dir(project_id)
    swallowed: list[str] = []

    def _on_error(func, path, exc_info):
        swallowed.append(f"{path}: {exc_info[1]}")

    if local_path.exists():
        shutil.rmtree(local_path, onerror=_on_error)
    if local_path.exists():
        raise RuntimeError(
            f"Local project cleanup incomplete: {local_path}; errors={swallowed[:5]}"
        )

    return {
        "status": "deleted",
        "project_id": str(project_id),
        "deleted_objects": deleted_objects,
        "local_path": str(local_path),
        "ignored_local_errors": len(swallowed),
    }
