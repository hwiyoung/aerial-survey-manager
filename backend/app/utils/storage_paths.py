"""Canonical storage keys and processing paths for project artifacts."""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path
from uuid import UUID

from app.config import get_settings


def project_id_str(project_id: str | UUID) -> str:
    return str(project_id)


def safe_filename(filename: str) -> str:
    return os.path.basename(str(filename or "").strip())


def project_prefix(project_id: str | UUID) -> str:
    return f"projects/{project_id_str(project_id)}"


def source_images_prefix(project_id: str | UUID) -> str:
    return f"{project_prefix(project_id)}/source/images/"


def source_image_key(project_id: str | UUID, filename: str) -> str:
    return f"{source_images_prefix(project_id)}{safe_filename(filename)}"


def is_source_image_key(object_name: str) -> bool:
    """Return True only for original project images, not thumbnails/exports."""
    parts = str(object_name or "").split("/")
    return (
        len(parts) >= 5
        and parts[0] == "projects"
        and bool(parts[1])
        and parts[2:4] == ["source", "images"]
        and all(parts[4:])
    )


def is_private_project_key(object_name: str) -> bool:
    """All project data is private outside the authenticated organization."""
    return str(object_name or "").startswith(("projects/", "orthomosaic/"))


def source_thumbnail_prefix(project_id: str | UUID) -> str:
    return f"{project_prefix(project_id)}/source/thumbnails/"


def source_thumbnail_key(project_id: str | UUID, filename: str) -> str:
    return f"{source_thumbnail_prefix(project_id)}{safe_filename(filename)}.jpg"


def project_exports_prefix(project_id: str | UUID) -> str:
    return f"{project_prefix(project_id)}/exports/"


def project_preview_key(project_id: str | UUID) -> str:
    return f"{project_exports_prefix(project_id)}result_thumb.png"


def orthomosaic_prefix() -> str:
    return "orthomosaic/"


def orthomosaic_project_prefix(project_id: str | UUID) -> str:
    """Return the legacy RC project prefix used only for cleanup/migration."""
    return f"{orthomosaic_prefix()}{project_id_str(project_id)}/"


def normalize_crs_label(value: str | None, default: str = "EPSG:5186") -> str:
    raw = str(value or default).strip().upper()
    if re.fullmatch(r"\d{4,5}", raw):
        raw = f"EPSG:{raw}"
    if not re.fullmatch(r"EPSG:\d{4,5}", raw):
        raw = default
    return raw.replace(":", "")


_FS_UNSAFE_RE = re.compile(r'[\\/:*?"<>|\x00-\x1f\s]+')
_UNDERSCORE_RUN_RE = re.compile(r"_{2,}")


def sanitize_filename_component(value: str | None, max_len: int = 100) -> str:
    """Make a string safe to use as a single filename component.

    Keeps Unicode letters (including 한글) and `.-_`; replaces filesystem-unsafe
    characters (`/ \\ : * ? " < > |`), control chars and whitespace with `_`.
    Collapses repeated underscores and trims leading/trailing separators.
    Returns "" when the input is empty/None or reduces to nothing.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""
    cleaned = _FS_UNSAFE_RE.sub("_", raw)
    cleaned = _UNDERSCORE_RUN_RE.sub("_", cleaned).strip("._-")
    return cleaned[:max_len].rstrip("._-")


def orthomosaic_key(
    project_id: str | UUID,
    target_crs: str | None = "EPSG:5186",
    when: datetime | None = None,
    region: str | None = None,
    title: str | None = None,
) -> str:
    """Compute the orthomosaic storage key / export filename.

    Final COGs use the deployment contract's flat
    ``orthomosaic/{region}_{title}.tif`` layout. A UUID/timestamp is used only
    when no usable title exists; it is part of the filename, never a directory.
    Job-specific isolation belongs in the processing work directory rather
    than the operator-facing final-output directory.
    """
    safe_title = sanitize_filename_component(title)
    if safe_title:
        safe_region = sanitize_filename_component(region)
        basename = f"{safe_region}_{safe_title}" if safe_region else safe_title
        return f"{orthomosaic_prefix()}{basename}.tif"

    stamp = (when or datetime.now()).strftime("%Y%m%d_%H%M%S")
    return (
        f"{orthomosaic_prefix()}{project_id_str(project_id)}_"
        f"orthomosaic_{normalize_crs_label(target_crs)}_{stamp}.tif"
    )


def numbered_orthomosaic_key(base_key: str, index: int) -> str:
    """Return a PC-style numbered variant of a flat orthomosaic key.

    ``index=0`` keeps the original name. Later variants use
    ``name (1).tif``, ``name (2).tif``, and so on.
    """
    key = str(base_key or "")
    path = Path(key)
    if (
        index < 0
        or not key.startswith(orthomosaic_prefix())
        or len(path.parts) != 2
        or path.suffix.lower() != ".tif"
    ):
        raise ValueError(f"Invalid flat orthomosaic key: {base_key}")
    if index == 0:
        return key
    return str(path.with_name(f"{path.stem} ({index}){path.suffix}"))


def is_numbered_orthomosaic_variant(candidate_key: str | None, base_key: str) -> bool:
    """Return whether ``candidate_key`` is the base key or its numbered form."""
    if not candidate_key:
        return False
    candidate = Path(str(candidate_key))
    base = Path(str(base_key))
    if candidate.parent != base.parent or candidate.suffix.lower() != base.suffix.lower():
        return False
    if candidate.name == base.name:
        return True
    return re.fullmatch(
        rf"{re.escape(base.stem)} \([1-9]\d*\){re.escape(base.suffix)}",
        candidate.name,
    ) is not None


def project_root_dir(project_id: str | UUID) -> Path:
    settings = get_settings()
    return Path(settings.PROCESSING_DATA_PATH) / project_id_str(project_id)


def processing_dir(project_id: str | UUID) -> Path:
    return project_root_dir(project_id) / "processing"


def processing_status_path(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / "status.json"


def processing_images_dir(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / "images"


def processing_metadata_path(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / "metadata.txt"


def processing_exclusion_path(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / ".excluded_images.txt"


def processing_work_dir(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / ".work"


def legacy_processing_work_dir(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / "metashape"


def processing_logs_dir(project_id: str | UUID) -> Path:
    return processing_dir(project_id) / ".logs"


def processing_log_path(project_id: str | UUID) -> Path:
    return processing_logs_dir(project_id) / "processing.log"
