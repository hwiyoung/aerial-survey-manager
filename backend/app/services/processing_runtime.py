"""Runtime helpers for processing status reconciliation."""
from __future__ import annotations

import ast
import json
import logging
import os
import time
from typing import Any
from uuid import UUID

from app.utils.storage_paths import (
    processing_status_path,
    processing_work_dir,
)

logger = logging.getLogger("app.processing.runtime")

PROCESSING_TASK_NAME = "app.workers.tasks.process_orthophoto"
ACTIVE_TASK_TTL_SECONDS = float(os.getenv("PROCESSING_ACTIVE_TASK_CACHE_TTL_SECONDS", "2.0"))
ACTIVE_TASK_INSPECT_TIMEOUT = float(os.getenv("PROCESSING_ACTIVE_TASK_INSPECT_TIMEOUT_SECONDS", "0.35"))

STEP_MESSAGE_MAP = {
    "Align Photos": "이미지 정렬 중...",
    "Build Depth Maps": "깊이 맵 생성 중...",
    "Build DEM": "수치표고모델 생성 중...",
    "Build Orthomosaic": "정사모자이크 생성 중...",
    "Export Raster": "정사영상 내보내기 중...",
    "Convert COG": "COG 변환 중...",
}
STEP_ORDER = tuple(STEP_MESSAGE_MAP.keys())

_ACTIVE_TASK_CACHE: dict[str, Any] = {
    "expires_at": 0.0,
    "tasks": {},
}


def _safe_uuid_text(value: object) -> str | None:
    if value in (None, ""):
        return None
    try:
        return str(UUID(str(value)))
    except Exception:
        return str(value)


def _decode_container(value: object) -> object:
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text:
        return value
    try:
        return ast.literal_eval(text)
    except Exception:
        try:
            return json.loads(text)
        except Exception:
            return value


def _extract_processing_task(task: dict[str, Any], worker_name: str) -> tuple[str, dict[str, Any]] | None:
    if task.get("name") != PROCESSING_TASK_NAME:
        return None

    args = _decode_container(task.get("args") or [])
    kwargs = _decode_container(task.get("kwargs") or {})
    if not isinstance(args, (list, tuple)):
        args = []
    if not isinstance(kwargs, dict):
        kwargs = {}

    job_id = kwargs.get("job_id") or (args[0] if len(args) >= 1 else None)
    project_id = kwargs.get("project_id") or (args[1] if len(args) >= 2 else None)
    project_id_text = _safe_uuid_text(project_id)
    if not project_id_text:
        return None

    return project_id_text, {
        "task_id": task.get("id"),
        "job_id": _safe_uuid_text(job_id),
        "project_id": project_id_text,
        "worker": worker_name,
    }


def get_active_processing_tasks(force_refresh: bool = False) -> dict[str, dict[str, Any]]:
    """Return active processing Celery tasks keyed by project id.

    Celery inspect is intentionally cached because project list/detail endpoints
    may call this frequently while the dashboard is polling.
    """
    now = time.monotonic()
    if not force_refresh and now < _ACTIVE_TASK_CACHE["expires_at"]:
        return dict(_ACTIVE_TASK_CACHE["tasks"])

    active_tasks: dict[str, dict[str, Any]] = {}
    try:
        from app.workers.tasks import celery_app

        inspect = celery_app.control.inspect(timeout=ACTIVE_TASK_INSPECT_TIMEOUT)
        active_by_worker = inspect.active() or {}
    except Exception as exc:
        logger.debug("Celery active inspect failed: %s", exc)
        active_by_worker = {}

    if isinstance(active_by_worker, dict):
        for worker_name, worker_tasks in active_by_worker.items():
            if not isinstance(worker_tasks, list):
                continue
            for task in worker_tasks:
                if not isinstance(task, dict):
                    continue
                extracted = _extract_processing_task(task, str(worker_name))
                if extracted:
                    project_id, payload = extracted
                    active_tasks[project_id] = payload

    _ACTIVE_TASK_CACHE["tasks"] = active_tasks
    _ACTIVE_TASK_CACHE["expires_at"] = now + ACTIVE_TASK_TTL_SECONDS
    return dict(active_tasks)


def clear_active_processing_task_cache() -> None:
    """Force the next status/list request to inspect Celery again."""
    _ACTIVE_TASK_CACHE["tasks"] = {}
    _ACTIVE_TASK_CACHE["expires_at"] = 0.0


def read_processing_status_file(project_id: object) -> dict[str, Any]:
    try:
        status_path = processing_status_path(project_id)
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        pass
    return {}


def read_step_status_file(project_id: object) -> dict[str, Any]:
    step_status: dict[str, Any] = {}
    try:
        status_path = processing_work_dir(project_id) / "status.json"
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                step_status.update(data)
    except Exception:
        pass

    try:
        manifest_path = processing_work_dir(project_id) / "processing_manifest.json"
        if manifest_path.exists():
            with open(manifest_path, "r", encoding="utf-8") as f:
                manifest = json.load(f)
            manifest_steps = manifest.get("steps", {}) if isinstance(manifest, dict) else {}
            if isinstance(manifest_steps, dict):
                for record in manifest_steps.values():
                    if not isinstance(record, dict):
                        continue
                    task_name = record.get("task_name")
                    if not task_name:
                        continue
                    status_value = record.get("status")
                    if status_value == "completed":
                        step_status[task_name] = 100
                    elif status_value == "failed":
                        step_status[task_name] = 1000
                    elif status_value == "running":
                        step_status.setdefault(task_name, 1)
    except Exception:
        pass

    return step_status


def read_processing_events(project_id: object, limit: int = 80) -> list[dict[str, Any]]:
    events_path = processing_work_dir(project_id) / "processing_events.log"
    if not events_path.exists():
        return []

    events: list[dict[str, Any]] = []
    try:
        with open(events_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-limit:]
        for line in lines:
            text = line.strip()
            if not text:
                continue
            try:
                payload = json.loads(text)
                if isinstance(payload, dict):
                    events.append(payload)
                    continue
            except json.JSONDecodeError:
                pass
            events.append({
                "timestamp": None,
                "level": "info",
                "message": text,
            })
    except OSError:
        return []
    return events


def _numeric_progress(value: object) -> float | None:
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except Exception:
        return None


def infer_message_from_step_status(step_status: dict[str, Any], fallback: str | None = None) -> str | None:
    if not isinstance(step_status, dict) or not step_status:
        return fallback

    for step_name in STEP_ORDER:
        value = _numeric_progress(step_status.get(step_name))
        if value is None:
            continue
        if 0 < value < 100:
            return STEP_MESSAGE_MAP[step_name]

    for step_name in STEP_ORDER:
        value = _numeric_progress(step_status.get(step_name))
        if value is None:
            continue
        if value < 100:
            return STEP_MESSAGE_MAP[step_name]

    return fallback


def progress_from_step_status(step_status: dict[str, Any], fallback: int | None = None) -> int:
    values: list[float] = []
    for step_name in STEP_ORDER:
        if step_name not in step_status:
            continue
        value = _numeric_progress(step_status.get(step_name))
        if value is None or value >= 1000:
            continue
        values.append(max(0.0, min(100.0, value)))

    if not values:
        return int(fallback or 0)

    step_progress = int(round(sum(values) / len(values)))
    return max(int(fallback or 0), step_progress)
