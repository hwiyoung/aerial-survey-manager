"""One-shot migration: rename existing orthomosaic files from the legacy
``{uuid}_orthomosaic_EPSG{n}_{stamp}.tif`` naming to the new
``{region}_{title}.tif`` scheme so existing artifacts match the convention
applied to new processing runs.

Usage (run inside the api container so DB + storage mounts are available):

    docker exec aerial-survey-manager-api-1 \\
        python /app/scripts/rename_orthomosaic_files.py            # dry-run
    docker exec aerial-survey-manager-api-1 \\
        python /app/scripts/rename_orthomosaic_files.py --apply    # execute

The script:
  * Only touches projects whose ``ortho_path`` matches the legacy regex.
  * Skips when the target name already exists, the source is missing,
    region/title sanitize to empty, or processing is in flight.
  * Renames the main `.tif` plus sidecars (`.aux.xml`, `.ovr`, `.msk`).
  * Updates ``projects.ortho_path``, all jobs pointing at the old key, and the
    latest ``processing_jobs.result_path`` for each project.
  * Writes a JSON backup of the rename plan to /tmp before applying so any
    failure can be reverted manually.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

# Make `app` importable when run via `python /app/scripts/...`
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import get_settings
from app.models.project import Project, ProcessingJob
from app.utils.db import sync_db_session
from app.utils.storage_paths import orthomosaic_key, orthomosaic_prefix

# Legacy key: orthomosaic/{uuid}_orthomosaic_EPSG{4-5}_{YYYYMMDD}_{HHMMSS}.tif
_LEGACY_KEY_RE = re.compile(
    r"^orthomosaic/"
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
    r"_orthomosaic_EPSG\d{4,5}_\d{8}_\d{6}\.tif$"
)

# GDAL sidecar suffixes to move alongside the main .tif.
_SIDECAR_SUFFIXES = (".aux.xml", ".ovr", ".msk", ".tif.aux.xml")


def _storage_root() -> Path:
    settings = get_settings()
    return Path(settings.LOCAL_STORAGE_PATH)


def _sidecars_for(path: Path) -> list[Path]:
    """Return existing sidecar files associated with a main .tif path."""
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


def _build_plan(db) -> tuple[list[dict], list[dict]]:
    """Return (plan, skipped) lists describing the proposed renames."""
    storage_root = _storage_root()
    plan: list[dict] = []
    skipped: list[dict] = []

    projects = (
        db.query(Project)
        .filter(Project.ortho_path.isnot(None))
        .order_by(Project.updated_at.desc())
        .all()
    )

    for project in projects:
        pid = str(project.id)
        old_key = str(project.ortho_path)

        if not _LEGACY_KEY_RE.match(old_key):
            skipped.append({
                "project_id": pid,
                "title": project.title,
                "reason": "already-new-format",
                "ortho_path": old_key,
            })
            continue

        new_key = orthomosaic_key(
            project.id,
            region=project.region,
            title=project.title,
        )
        if new_key == old_key:
            # title/region sanitized to empty → fell back to legacy format.
            skipped.append({
                "project_id": pid,
                "title": project.title,
                "reason": "sanitized-name-empty",
                "ortho_path": old_key,
            })
            continue

        if not new_key.startswith(orthomosaic_prefix()):
            skipped.append({
                "project_id": pid,
                "title": project.title,
                "reason": f"unexpected-new-key: {new_key}",
                "ortho_path": old_key,
            })
            continue

        old_path = storage_root / old_key
        new_path = storage_root / new_key

        if not old_path.exists():
            skipped.append({
                "project_id": pid,
                "title": project.title,
                "reason": f"source-missing: {old_path}",
                "ortho_path": old_key,
            })
            continue

        if new_path.exists():
            skipped.append({
                "project_id": pid,
                "title": project.title,
                "reason": f"target-exists: {new_path.name}",
                "ortho_path": old_key,
            })
            continue

        sidecars = _sidecars_for(old_path)
        sidecar_moves = [
            (sc, Path(str(new_path) + sc.name[len(old_path.name):]))
            for sc in sidecars
        ]

        plan.append({
            "project_id": pid,
            "title": project.title,
            "region": project.region,
            "old_key": old_key,
            "new_key": new_key,
            "old_path": str(old_path),
            "new_path": str(new_path),
            "sidecars": [(str(a), str(b)) for a, b in sidecar_moves],
            "file_size": old_path.stat().st_size,
        })

    return plan, skipped


def _check_in_flight(db) -> list[dict]:
    """Return any in-flight jobs that would conflict with renaming."""
    in_flight = (
        db.query(ProcessingJob)
        .filter(ProcessingJob.status.in_(("queued", "processing")))
        .all()
    )
    return [
        {
            "job_id": str(j.id),
            "project_id": str(j.project_id),
            "status": j.status,
            "progress": j.progress,
        }
        for j in in_flight
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

    for i, item in enumerate(plan, 1):
        size_gb = item["file_size"] / (1024 ** 3)
        print(
            f"[{i:>2}] {item['project_id'][:8]}  "
            f"region={item['region']!r:>20}  title={item['title']!r}"
        )
        print(f"     OLD: {item['old_key']}  ({size_gb:.2f} GiB)")
        print(f"     NEW: {item['new_key']}")
        for sc_old, sc_new in item["sidecars"]:
            print(f"     +sidecar  {Path(sc_old).name}  →  {Path(sc_new).name}")
        print()

    if skipped:
        print(f"--- SKIPPED ({len(skipped)}) ---")
        for item in skipped:
            print(
                f"  {item['project_id'][:8]}  "
                f"title={item.get('title')!r}  reason={item['reason']}"
            )
        print()


def _apply_plan(db, plan: list[dict]) -> tuple[int, int]:
    success = 0
    failure = 0
    for item in plan:
        old_path = Path(item["old_path"])
        new_path = Path(item["new_path"])
        moved_sidecars: list[tuple[Path, Path]] = []
        try:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            os.rename(old_path, new_path)
            for sc_old_s, sc_new_s in item["sidecars"]:
                sc_old = Path(sc_old_s)
                sc_new = Path(sc_new_s)
                if sc_old.exists():
                    os.rename(sc_old, sc_new)
                    moved_sidecars.append((sc_old, sc_new))

            project = db.query(Project).filter(
                Project.id == item["project_id"]
            ).first()
            if project is not None:
                project.ortho_path = item["new_key"]

            jobs = db.query(ProcessingJob).filter(
                ProcessingJob.project_id == item["project_id"],
                ProcessingJob.result_path == item["old_key"],
            ).all()
            updated_job_ids = set()
            for j in jobs:
                j.result_path = item["new_key"]
                updated_job_ids.add(j.id)

            latest_job = _latest_job_for_project(db, item["project_id"])
            if latest_job is not None and latest_job.id not in updated_job_ids:
                latest_job.result_path = item["new_key"]

            db.commit()
            success += 1
            print(f"  ✅ {item['project_id'][:8]}  →  {Path(item['new_key']).name}")
        except Exception as exc:
            db.rollback()
            # Best-effort filesystem rollback so DB and disk stay consistent.
            try:
                if new_path.exists() and not old_path.exists():
                    os.rename(new_path, old_path)
            except OSError as roll_exc:
                print(f"     ⚠️ disk rollback failed: {roll_exc}")
            for sc_old, sc_new in moved_sidecars:
                try:
                    if sc_new.exists() and not sc_old.exists():
                        os.rename(sc_new, sc_old)
                except OSError as roll_exc:
                    print(f"     ⚠️ sidecar rollback failed ({sc_new}): {roll_exc}")
            failure += 1
            print(f"  ❌ {item['project_id'][:8]}  failed: {exc}")

    return success, failure


def main() -> int:
    apply = "--apply" in sys.argv

    with sync_db_session() as db:
        in_flight = _check_in_flight(db)
        if in_flight:
            print("❌ 진행 중인 처리 작업이 있어 마이그레이션을 중단합니다:")
            for j in in_flight:
                print(
                    f"   - job={j['job_id'][:8]}.. project={j['project_id'][:8]}.. "
                    f"status={j['status']} progress={j['progress']}"
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
        backup_path = Path(f"/tmp/orthomosaic_rename_backup_{stamp}.json")
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
