"""Bounded project processing logs and failure diagnostics."""
from __future__ import annotations

import io
import json
import logging
import os
import re
import tarfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import get_settings
from app.utils.storage_paths import (
    processing_log_path,
    processing_logs_dir,
    processing_status_path,
    processing_work_dir,
)

logger = logging.getLogger(__name__)
settings = get_settings()

_SAFE_REFERENCE_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _rotated_log_path(log_path: Path, index: int) -> Path:
    return log_path.with_name(f"{log_path.name}.{index}")


def rotate_processing_log(log_path: Path) -> bool:
    """Rotate a project log when it reaches the configured size."""
    max_bytes = max(1, int(settings.PROCESSING_LOG_MAX_BYTES))
    backup_count = max(0, int(settings.PROCESSING_LOG_BACKUP_COUNT))
    try:
        if not log_path.exists() or log_path.stat().st_size < max_bytes:
            return False
        if backup_count == 0:
            with open(log_path, "w", encoding="utf-8"):
                pass
            return True

        log_path.parent.mkdir(parents=True, exist_ok=True)
        for index in range(backup_count, 1, -1):
            source = _rotated_log_path(log_path, index - 1)
            if source.exists():
                os.replace(source, _rotated_log_path(log_path, index))
        os.replace(log_path, _rotated_log_path(log_path, 1))
        return True
    except OSError as exc:
        logger.warning("processing_log_rotation_failed path=%s error=%s", log_path, exc)
        return False


def append_processing_log(log_path: Path, text: str) -> None:
    """Append text while applying rotation before and after the write."""
    rotate_processing_log(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as log_file:
        log_file.write(text)
    rotate_processing_log(log_path)


def finalize_processing_log(log_path: Path) -> None:
    """Apply the size boundary after a subprocess closes its log handle."""
    rotate_processing_log(log_path)


@contextmanager
def processing_log_writer(log_path: Path):
    """Open a project log for append and rotate it after every exit path."""
    rotate_processing_log(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(log_path, "a", encoding="utf-8") as log_file:
            yield log_file
    finally:
        finalize_processing_log(log_path)


def read_processing_log_tail(log_path: Path, lines: int = 20) -> str:
    """Read the newest available project log tail, including a just-rotated file."""
    candidates = [log_path]
    candidates.extend(
        _rotated_log_path(log_path, index)
        for index in range(1, max(0, int(settings.PROCESSING_LOG_BACKUP_COUNT)) + 1)
    )
    remaining = max(1, lines)
    collected: list[str] = []
    for candidate in candidates:
        try:
            if not candidate.exists():
                continue
            with open(candidate, encoding="utf-8", errors="replace") as log_file:
                content = log_file.readlines()
            selected = content[-remaining:]
            collected = selected + collected
            remaining -= len(selected)
            if remaining <= 0:
                break
        except OSError:
            continue
    return "".join(collected) if collected else "(로그 파일 읽기 실패)"


def _tail_bytes(path: Path, limit: int) -> bytes:
    with open(path, "rb") as source:
        size = path.stat().st_size
        if size > limit:
            source.seek(size - limit)
        return source.read()


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mtime = int(datetime.now(tz=timezone.utc).timestamp())
    info.mode = 0o600
    archive.addfile(info, io.BytesIO(payload))


def _bundle_files(project_id: str) -> list[tuple[Path, str, bool]]:
    log_path = processing_log_path(project_id)
    files: list[tuple[Path, str, bool]] = [(log_path, "logs/processing.log", True)]
    files.extend(
        (
            _rotated_log_path(log_path, index),
            f"logs/processing.log.{index}",
            True,
        )
        for index in range(1, max(0, int(settings.PROCESSING_LOG_BACKUP_COUNT)) + 1)
    )
    work_dir = processing_work_dir(project_id)
    files.extend(
        [
            (processing_status_path(project_id), "state/status.json", False),
            (work_dir / "status.json", "state/step_status.json", False),
            (work_dir / "processing_manifest.json", "state/processing_manifest.json", False),
            (work_dir / "auto_export_status.json", "state/auto_export_status.json", False),
            (work_dir / ".auto_export.log", "logs/auto_export.log", True),
        ]
    )
    files.extend(
        (
            _rotated_log_path(work_dir / ".auto_export.log", index),
            f"logs/auto_export.log.{index}",
            True,
        )
        for index in range(1, max(0, int(settings.PROCESSING_LOG_BACKUP_COUNT)) + 1)
    )
    return files


def processing_error_bundles_dir(project_id: str) -> Path:
    return processing_logs_dir(project_id) / "errors"


def create_processing_error_bundle(
    project_id: str,
    error_reference: str,
    *,
    error_code: str,
    job_id: str | None = None,
    technical_error: str | None = None,
) -> Path | None:
    """Atomically preserve recent diagnostics for an internal error reference."""
    safe_reference = _SAFE_REFERENCE_RE.sub("_", error_reference).strip("_") or "unknown"
    created_at = datetime.now(tz=timezone.utc)
    bundle_dir = processing_error_bundles_dir(project_id)
    bundle_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = bundle_dir / f"{created_at.strftime('%Y%m%dT%H%M%SZ')}_{safe_reference}.tar.gz"
    temp_path = bundle_path.with_suffix(bundle_path.suffix + ".tmp")
    metadata: dict[str, Any] = {
        "created_at": created_at.isoformat(),
        "project_id": str(project_id),
        "job_id": str(job_id) if job_id else None,
        "error_code": error_code,
        "error_reference": error_reference,
        "technical_error": technical_error,
        "policy": {
            "retention_days": int(settings.PROCESSING_ERROR_BUNDLE_RETENTION_DAYS),
            "project_limit": int(settings.PROCESSING_ERROR_BUNDLE_PROJECT_LIMIT),
            "total_max_bytes": int(settings.PROCESSING_ERROR_BUNDLE_TOTAL_MAX_BYTES),
        },
    }

    try:
        with tarfile.open(temp_path, "w:gz") as archive:
            _add_bytes(
                archive,
                "metadata.json",
                (json.dumps(metadata, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
            )
            tail_limit = max(1, int(settings.PROCESSING_ERROR_BUNDLE_LOG_TAIL_BYTES))
            for source, archive_name, tail_only in _bundle_files(str(project_id)):
                if not source.is_file():
                    continue
                payload = _tail_bytes(source, tail_limit) if tail_only else source.read_bytes()
                _add_bytes(archive, archive_name, payload)
        os.replace(temp_path, bundle_path)
        cleanup_processing_error_bundles()
        return bundle_path if bundle_path.exists() else None
    except Exception as exc:
        logger.warning(
            "processing_error_bundle_failed project_id=%s reference_id=%s error=%s",
            project_id,
            error_reference,
            exc,
        )
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        return None


def _all_error_bundles() -> list[Path]:
    root = Path(settings.PROCESSING_DATA_PATH)
    if not root.exists():
        return []
    return [path for path in root.glob("*/processing/.logs/errors/*.tar.gz") if path.is_file()]


def cleanup_processing_error_bundles(now: datetime | None = None) -> dict[str, int]:
    """Enforce age, per-project count, and global-size retention limits."""
    current_time = now or datetime.now(tz=timezone.utc)
    cutoff = current_time.timestamp() - max(
        0,
        int(settings.PROCESSING_ERROR_BUNDLE_RETENTION_DAYS),
    ) * 86400
    project_limit = max(0, int(settings.PROCESSING_ERROR_BUNDLE_PROJECT_LIMIT))
    total_limit = max(0, int(settings.PROCESSING_ERROR_BUNDLE_TOTAL_MAX_BYTES))
    removed_files = 0
    removed_bytes = 0

    def remove(path: Path) -> None:
        nonlocal removed_files, removed_bytes
        try:
            size = path.stat().st_size
            path.unlink()
            removed_files += 1
            removed_bytes += size
        except OSError as exc:
            logger.warning("processing_error_bundle_cleanup_failed path=%s error=%s", path, exc)

    bundles = _all_error_bundles()
    for bundle in bundles:
        try:
            if bundle.stat().st_mtime < cutoff:
                remove(bundle)
        except OSError:
            continue

    by_project: dict[Path, list[Path]] = {}
    for bundle in _all_error_bundles():
        by_project.setdefault(bundle.parent, []).append(bundle)
    for project_bundles in by_project.values():
        project_bundles.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for bundle in project_bundles[project_limit:]:
            remove(bundle)

    remaining = _all_error_bundles()
    remaining.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    total_bytes = sum(path.stat().st_size for path in remaining)
    while remaining and total_bytes > total_limit:
        oldest = remaining.pop()
        try:
            size = oldest.stat().st_size
        except OSError:
            continue
        remove(oldest)
        total_bytes -= size

    return {
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "remaining_files": len(_all_error_bundles()),
    }
