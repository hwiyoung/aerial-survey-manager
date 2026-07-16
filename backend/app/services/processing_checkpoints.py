"""Read-only checkpoint inspection used by processing restart APIs."""
from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from app.services.processing_steps import (
    CHECKPOINT_STEP_LABELS,
    PROJECT_STATE_STEP_RANK,
)
from app.utils.storage_paths import processing_work_dir


def project_checkpoint_covers(work_dir: Path, script_name: str) -> bool:
    checkpoint_dir = work_dir / ".processing_checkpoint"
    if not (
        (checkpoint_dir / "project.psx").exists()
        and (checkpoint_dir / "project.files").exists()
    ):
        return False
    try:
        checkpoint_step = (checkpoint_dir / "step.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    checkpoint_rank = PROJECT_STATE_STEP_RANK.get(checkpoint_step)
    requested_rank = PROJECT_STATE_STEP_RANK.get(script_name)
    return bool(checkpoint_rank and requested_rank and checkpoint_rank >= requested_rank)


def step_checkpoint_usable(work_dir: Path, script_name: str) -> bool:
    if script_name in PROJECT_STATE_STEP_RANK:
        return project_checkpoint_covers(work_dir, script_name)
    if script_name == "export_orthomosaic.py":
        return (work_dir / "result.tif").exists()
    if script_name == "convert_cog.py":
        return (work_dir / "result_cog.tif").exists()
    return False


def summarize_processing_restart(work_dir: Path) -> dict:
    manifest_path = work_dir / "processing_manifest.json"
    summary = {
        "can_resume": False,
        "completed_steps": [],
        "failed_step": None,
        "next_step": None,
        "manifest_exists": manifest_path.exists(),
    }
    if not manifest_path.exists():
        return summary

    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return summary

    steps = manifest.get("steps", {})
    if not isinstance(steps, dict):
        return summary

    completed = []
    failed_step = None
    next_step = None
    for script_name, record in steps.items():
        if not isinstance(record, dict):
            continue
        label = CHECKPOINT_STEP_LABELS.get(script_name) or record.get("task_name") or script_name
        status_value = record.get("status")
        if status_value == "completed" and step_checkpoint_usable(work_dir, script_name):
            completed.append({
                "script": script_name,
                "label": label,
                "completed_at": record.get("completed_at"),
            })
            continue
        if status_value == "failed" and failed_step is None:
            failed_step = {
                "script": script_name,
                "label": label,
                "error_code": record.get("error_code"),
                "error_message": record.get("error_message"),
            }
        if next_step is None:
            next_step = {
                "script": script_name,
                "label": label,
                "status": status_value or "pending",
            }

    summary["can_resume"] = bool(completed)
    summary["completed_steps"] = completed
    summary["failed_step"] = failed_step
    summary["next_step"] = next_step
    return summary


def processing_restart_summary(project_id: UUID) -> dict:
    return summarize_processing_restart(processing_work_dir(project_id))
