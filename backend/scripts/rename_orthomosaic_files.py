"""One-shot migration to the flat orthomosaic output layout.

Supported source layouts:

* ``orthomosaic/{uuid}_orthomosaic_EPSG{n}_{stamp}.tif``
* ``orthomosaic/{project_uuid}/{name}_{job_uuid}.tif`` from v2.0.0-rc.1

The target is ``orthomosaic/{region}_{title}.tif``. If that name is occupied,
the first PC-style numbered variant is used (``name (1).tif``, ``name
(2).tif``, ...).

Usage (run inside the API container so DB and storage mounts are available):

    python /app/scripts/rename_orthomosaic_files.py            # dry-run
    python /app/scripts/rename_orthomosaic_files.py --apply    # execute

The script:

* Supports local storage only because files and DB paths must move together.
* Only touches the current COG referenced by ``projects.ortho_path``.
* Stops before apply when any processing job is in flight.
* Skips missing sources, invalid names, and RC UUID directories that contain
  extra files. Existing targets receive an automatic numbered filename.
* Moves the main TIFF and known GDAL sidecars together.
* Updates ``projects.ortho_path``, jobs pointing at the old key, and the latest
  processing job for the project.
* Writes a persistent JSON mapping backup under the orthomosaic root before
  applying.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Make `app` importable when run via `python /app/scripts/...`.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings
from app.models.project import ProcessingJob, Project
from app.utils.db import sync_db_session
from app.utils.storage_paths import (
    numbered_orthomosaic_key,
    orthomosaic_key,
    orthomosaic_prefix,
    sanitize_filename_component,
)

_UUID_PATTERN = (
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
    r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_LEGACY_KEY_RE = re.compile(
    r"^orthomosaic/"
    + _UUID_PATTERN
    + r"_orthomosaic_EPSG\d{4,5}_\d{8}_\d{6}\.tif$"
)
_RC_UUID_KEY_RE = re.compile(
    r"^orthomosaic/(?P<project_id>"
    + _UUID_PATTERN
    + r")/(?P<filename>[^/]+\.tif)$"
)
_SIDECAR_SUFFIXES = (".aux.xml", ".ovr", ".msk", ".tif.aux.xml")


def _storage_root() -> Path:
    return Path(get_settings().LOCAL_STORAGE_PATH)


def _sidecars_for(path: Path) -> list[Path]:
    """Return existing GDAL sidecars associated with one TIFF."""
    found: list[Path] = []
    seen: set[str] = set()
    for suffix in _SIDECAR_SUFFIXES:
        candidate = Path(str(path) + suffix)
        if str(candidate) in seen:
            continue
        if candidate.exists():
            seen.add(str(candidate))
            found.append(candidate)
    return found


def _source_format(old_key: str, project_id: str) -> str | None:
    if _LEGACY_KEY_RE.fullmatch(old_key):
        return "legacy-flat-uuid"

    rc_match = _RC_UUID_KEY_RE.fullmatch(old_key)
    if rc_match and rc_match.group("project_id").lower() == project_id.lower():
        return "rc-project-directory"
    return None


def _unexpected_rc_siblings(old_path: Path, sidecars: list[Path]) -> list[str]:
    """Return entries that prevent safely removing an RC UUID directory."""
    allowed = {old_path.resolve(), *(path.resolve() for path in sidecars)}
    return sorted(
        str(path)
        for path in old_path.parent.iterdir()
        if path.resolve() not in allowed
    )


def _skip(project, reason: str, old_key: str, **details) -> dict:
    return {
        "project_id": str(project.id),
        "title": project.title,
        "reason": reason,
        "ortho_path": old_key,
        **details,
    }


def _build_plan(db) -> tuple[list[dict], list[dict]]:
    """Return ``(plan, skipped)`` for the proposed filesystem and DB moves."""
    storage_root = _storage_root()
    candidates: list[dict] = []
    skipped: list[dict] = []

    projects = (
        db.query(Project)
        .filter(Project.ortho_path.isnot(None))
        .order_by(Project.updated_at.desc())
        .all()
    )

    for project in projects:
        project_id = str(project.id)
        old_key = str(project.ortho_path)
        source_format = _source_format(old_key, project_id)
        if source_format is None:
            skipped.append(
                _skip(project, "already-flat-or-unsupported-format", old_key)
            )
            continue

        if not sanitize_filename_component(project.title):
            skipped.append(_skip(project, "sanitized-title-empty", old_key))
            continue

        base_key = orthomosaic_key(
            project.id,
            region=project.region,
            title=project.title,
        )
        if not base_key.startswith(orthomosaic_prefix()):
            skipped.append(
                _skip(project, f"unexpected-new-key: {base_key}", old_key)
            )
            continue

        old_path = storage_root / old_key
        if not old_path.exists():
            skipped.append(
                _skip(project, f"source-missing: {old_path}", old_key)
            )
            continue

        sidecars = _sidecars_for(old_path)
        if source_format == "rc-project-directory":
            extra_files = _unexpected_rc_siblings(old_path, sidecars)
            if extra_files:
                skipped.append(
                    _skip(
                        project,
                        "rc-project-directory-has-extra-files",
                        old_key,
                        extra_files=extra_files,
                    )
                )
                continue

        candidates.append(
            {
                "project_id": project_id,
                "title": project.title,
                "region": project.region,
                "source_format": source_format,
                "old_key": old_key,
                "base_key": base_key,
                "old_path": str(old_path),
                "source_sidecars": [str(sidecar) for sidecar in sidecars],
                "file_size": old_path.stat().st_size,
            }
        )

    # Reserve every flat key already referenced by DB, even if its physical
    # file is temporarily missing. Also reserve untracked flat TIFFs on disk.
    reserved_keys: set[str] = set()
    for project in projects:
        key = str(project.ortho_path or "")
        path = Path(key)
        if (
            key.startswith(orthomosaic_prefix())
            and len(path.parts) == 2
            and path.suffix.lower() == ".tif"
        ):
            reserved_keys.add(key)

    flat_root = storage_root / orthomosaic_prefix()
    if flat_root.exists():
        for path in flat_root.iterdir():
            if path.is_file() and path.suffix.lower() == ".tif":
                reserved_keys.add(path.relative_to(storage_root).as_posix())

    plan: list[dict] = []
    for item in candidates:
        old_path = Path(item["old_path"])
        selected = None
        for index in range(10_000):
            new_key = numbered_orthomosaic_key(item["base_key"], index)
            new_path = storage_root / new_key
            sidecar_moves = [
                (
                    Path(old_sidecar),
                    Path(
                        str(new_path)
                        + Path(old_sidecar).name[len(old_path.name) :]
                    ),
                )
                for old_sidecar in item["source_sidecars"]
            ]
            if new_key in reserved_keys or new_path.exists():
                continue
            if any(new_sidecar.exists() for _, new_sidecar in sidecar_moves):
                continue
            selected = {
                **item,
                "new_key": new_key,
                "new_path": str(new_path),
                "sidecars": [
                    (str(old_sidecar), str(new_sidecar))
                    for old_sidecar, new_sidecar in sidecar_moves
                ],
            }
            selected.pop("base_key", None)
            selected.pop("source_sidecars", None)
            break

        if selected is None:
            skipped.append(
                {
                    "project_id": item["project_id"],
                    "title": item["title"],
                    "reason": "numbered-target-exhausted",
                    "ortho_path": item["old_key"],
                }
            )
            continue
        reserved_keys.add(selected["new_key"])
        plan.append(selected)

    return plan, skipped


def _check_in_flight(db) -> list[dict]:
    """Return processing jobs that make file migration unsafe."""
    jobs = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status.in_(("scheduled", "queued", "processing")))
        .all()
    )
    return [
        {
            "job_id": str(job.id),
            "project_id": str(job.project_id),
            "status": job.status,
            "progress": job.progress,
        }
        for job in jobs
    ]


def _latest_job_for_project(db, project_id: str) -> ProcessingJob | None:
    return (
        db.query(ProcessingJob)
        .filter(ProcessingJob.project_id == project_id)
        .order_by(
            ProcessingJob.started_at.desc().nullslast(),
            ProcessingJob.completed_at.desc().nullslast(),
        )
        .first()
    )


def _print_plan(plan: list[dict], skipped: list[dict]) -> None:
    print(f"\n{'=' * 78}")
    print(f"  Migration plan: {len(plan)} rename, {len(skipped)} skip")
    print(f"{'=' * 78}\n")

    for index, item in enumerate(plan, 1):
        size_gib = item["file_size"] / (1024**3)
        print(
            f"[{index:>2}] {item['project_id'][:8]}  "
            f"region={item['region']!r:>20}  title={item['title']!r}"
        )
        print(f"     TYPE: {item['source_format']}")
        print(f"     OLD: {item['old_key']}  ({size_gib:.2f} GiB)")
        print(f"     NEW: {item['new_key']}")
        for old_sidecar, new_sidecar in item["sidecars"]:
            print(
                f"     +sidecar  {Path(old_sidecar).name}"
                f"  →  {Path(new_sidecar).name}"
            )
        print()

    if skipped:
        print(f"--- SKIPPED ({len(skipped)}) ---")
        for item in skipped:
            print(
                f"  {item['project_id'][:8]}  "
                f"title={item.get('title')!r}  reason={item['reason']}"
            )
            for extra_file in item.get("extra_files", []):
                print(f"     extra: {extra_file}")
        print()


def _apply_plan(db, plan: list[dict]) -> tuple[int, int]:
    success = 0
    failure = 0
    for item in plan:
        old_path = Path(item["old_path"])
        new_path = Path(item["new_path"])
        moved_sidecars: list[tuple[Path, Path]] = []
        removed_old_parent = False
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old_path, new_path)
            for old_sidecar_value, new_sidecar_value in item["sidecars"]:
                old_sidecar = Path(old_sidecar_value)
                new_sidecar = Path(new_sidecar_value)
                if old_sidecar.exists():
                    os.rename(old_sidecar, new_sidecar)
                    moved_sidecars.append((old_sidecar, new_sidecar))

            if (
                item["source_format"] == "rc-project-directory"
                and old_path.parent.exists()
                and not any(old_path.parent.iterdir())
            ):
                old_path.parent.rmdir()
                removed_old_parent = True

            project = db.query(Project).filter(
                Project.id == item["project_id"]
            ).first()
            if project is None:
                raise RuntimeError("project disappeared during migration")
            project.ortho_path = item["new_key"]

            jobs = db.query(ProcessingJob).filter(
                ProcessingJob.project_id == item["project_id"],
                ProcessingJob.result_path == item["old_key"],
            ).all()
            updated_job_ids = set()
            for job in jobs:
                job.result_path = item["new_key"]
                updated_job_ids.add(job.id)

            latest_job = _latest_job_for_project(db, item["project_id"])
            if latest_job is not None and latest_job.id not in updated_job_ids:
                latest_job.result_path = item["new_key"]

            db.commit()
            success += 1
            print(f"  ✅ {item['project_id'][:8]}  →  {item['new_key']}")
        except Exception as exc:
            db.rollback()
            try:
                if removed_old_parent:
                    old_path.parent.mkdir(parents=True, exist_ok=True)
                if new_path.exists() and not old_path.exists():
                    os.rename(new_path, old_path)
            except OSError as rollback_error:
                print(f"     ⚠️ disk rollback failed: {rollback_error}")
            for old_sidecar, new_sidecar in moved_sidecars:
                try:
                    if new_sidecar.exists() and not old_sidecar.exists():
                        os.rename(new_sidecar, old_sidecar)
                except OSError as rollback_error:
                    print(
                        f"     ⚠️ sidecar rollback failed ({new_sidecar}): "
                        f"{rollback_error}"
                    )
            failure += 1
            print(f"  ❌ {item['project_id'][:8]}  failed: {exc}")

    return success, failure


def main() -> int:
    apply = "--apply" in sys.argv
    settings = get_settings()
    if settings.STORAGE_BACKEND != "local":
        print(
            "❌ 이 마이그레이션은 STORAGE_BACKEND=local 전용입니다. "
            "MinIO 객체는 별도 절차가 필요합니다."
        )
        return 2

    with sync_db_session() as db:
        in_flight = _check_in_flight(db)
        if in_flight:
            print("❌ 진행 중인 처리 작업이 있어 마이그레이션을 중단합니다:")
            for job in in_flight:
                print(
                    f"   - job={job['job_id'][:8]}.. "
                    f"project={job['project_id'][:8]}.. "
                    f"status={job['status']} progress={job['progress']}"
                )
            print("   처리가 끝난 후 다시 실행해주세요.")
            return 2

        plan, skipped = _build_plan(db)
        _print_plan(plan, skipped)
        if not plan:
            print("이름을 변경할 대상이 없습니다.")
            return 0

        if not apply:
            print("[DRY-RUN] 실제 적용은 `--apply` 인자를 추가해 다시 실행하세요.")
            return 0

        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = _storage_root() / orthomosaic_prefix() / ".migration-backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / f"orthomosaic_rename_backup_{stamp}.json"
        backup_path.write_text(
            json.dumps(plan, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print(f"📦 매핑 백업 저장: {backup_path}\n")

        success, failure = _apply_plan(db, plan)
        print(f"\n=== 완료: {success} 성공 / {failure} 실패 ===")
        return 0 if failure == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
