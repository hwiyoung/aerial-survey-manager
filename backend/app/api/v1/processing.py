"""Processing API endpoints."""
import json
import math
import os
from collections import Counter
from uuid import UUID
from datetime import datetime
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Header,
    Query,
    status,
    WebSocket,
    WebSocketDisconnect,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import case, select, func
from pathlib import Path

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob, Image, ExteriorOrientation
from app.schemas.project import (
    ProcessingEnginesResponse,
    ProcessingEnginePolicy,
    ProcessingOptions,
    ProcessingJobResponse,
    ProcessingMetricsResponse,
    ProcessingMetricJobSummary,
    ProcessingMetricsSummary,
)
from app.auth.jwt import (
    get_current_user,
    PermissionChecker,
    is_admin_role,
    verify_internal_token,
    verify_token,
)
from app.utils.storage_paths import (
    processing_metadata_path,
    processing_status_path,
    processing_work_dir,
)
from app.services.processing_runtime import (
    clear_active_processing_task_cache,
    get_active_processing_tasks,
    infer_message_from_step_status,
    progress_from_step_status,
    read_processing_events as _read_processing_events,
    read_processing_status_file as _read_processing_status_file,
    read_step_status_file as _read_step_status_file,
)

router = APIRouter(prefix="/processing", tags=["Processing"])
DEFAULT_PROCESSING_ENGINE = "metashape"
PROCESSING_QUEUE = os.getenv("PROCESSING_ENGINE_QUEUE", "gpu-engine")
TERMINAL_PROCESSING_STATUSES = {"error", "failed", "cancelled"}
CANCELLED_PROCESSING_MESSAGE = "처리가 취소되었습니다."
RESTART_CHOICE_STATUSES = {"error", "failed", "cancelled"}
CHECKPOINT_STEP_LABELS = {
    "align_photos.py": "이미지 정렬",
    "build_depth_maps.py": "깊이 맵 생성",
    "build_point_cloud.py": "포인트 클라우드 생성",
    "build_dem.py": "수치표고모델 생성",
    "build_orthomosaic.py": "정사모자이크 생성",
    "export_orthomosaic.py": "정사영상 내보내기",
    "convert_cog.py": "COG 변환",
}
PROJECT_STATE_STEP_RANK = {
    "align_photos.py": 1,
    "build_depth_maps.py": 2,
    "build_point_cloud.py": 3,
    "build_dem.py": 4,
    "build_orthomosaic.py": 5,
}


def _remove_queued_celery_message(task_id: str | None, queue_name: str) -> int:
    """Remove a not-yet-reserved Celery message from a Redis list queue."""
    if not task_id:
        return 0
    try:
        import redis

        client = redis.Redis.from_url(get_settings().REDIS_URL, decode_responses=True)
        removed = 0
        for item in client.lrange(queue_name, 0, -1):
            if task_id in item:
                removed += client.lrem(queue_name, 0, item)
        if removed:
            print(f"[processing.cancel] removed {removed} queued Celery message(s): {task_id}")
        return removed
    except Exception as exc:
        print(f"[processing.cancel] failed to remove queued Celery message {task_id}: {exc}")
        return 0


def _write_processing_terminal_status_file(
    project_id: UUID,
    status_value: str,
    progress: int,
    message: str,
    metrics: dict | None = None,
) -> None:
    try:
        status_file = processing_status_path(project_id)
        status_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "status": status_value,
            "progress": max(0, min(100, int(progress or 0))),
            "message": message,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if metrics:
            payload["metrics"] = metrics
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        print(f"[processing.status] failed to write terminal status file: {exc}")


def _mark_job_cancelled(
    project: Project,
    job: ProcessingJob,
    *,
    progress: int | None = None,
    message: str = CANCELLED_PROCESSING_MESSAGE,
) -> int:
    cancel_progress = max(
        0,
        min(100, int(progress if progress is not None else (job.progress or project.progress or 0))),
    )
    job.status = "cancelled"
    job.progress = cancel_progress
    job.completed_at = job.completed_at or datetime.utcnow()
    job.error_message = None
    project.status = "cancelled"
    project.progress = cancel_progress
    _write_processing_terminal_status_file(
        job.project_id,
        "cancelled",
        cancel_progress,
        message,
    )
    return cancel_progress


def _celery_task_state(task_id: str | None) -> str | None:
    if not task_id:
        return None
    try:
        from app.workers.tasks import celery_app

        return celery_app.AsyncResult(task_id).state
    except Exception as exc:
        print(f"[processing.status] failed to read Celery task state {task_id}: {exc}")
        return None


def _project_checkpoint_covers(work_dir: Path, script_name: str) -> bool:
    checkpoint_dir = work_dir / ".processing_checkpoint"
    if not ((checkpoint_dir / "project.psx").exists() and (checkpoint_dir / "project.files").exists()):
        return False
    try:
        checkpoint_step = (checkpoint_dir / "step.txt").read_text(encoding="utf-8").strip()
    except OSError:
        return False
    checkpoint_rank = PROJECT_STATE_STEP_RANK.get(checkpoint_step)
    requested_rank = PROJECT_STATE_STEP_RANK.get(script_name)
    return bool(checkpoint_rank and requested_rank and checkpoint_rank >= requested_rank)


def _step_checkpoint_usable(work_dir: Path, script_name: str) -> bool:
    if script_name in PROJECT_STATE_STEP_RANK:
        return _project_checkpoint_covers(work_dir, script_name)
    if script_name == "export_orthomosaic.py":
        return (work_dir / "result.tif").exists()
    if script_name == "convert_cog.py":
        return (work_dir / "result_cog.tif").exists()
    return False


def _processing_restart_summary(project_id: UUID) -> dict:
    work_dir = processing_work_dir(project_id)
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
        if status_value == "completed" and _step_checkpoint_usable(work_dir, script_name):
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


def _get_processing_engine_policies():
    settings = get_settings()
    return {
        "metashape": {
            "enabled": settings.ENABLE_METASHAPE_ENGINE,
            "reason": "활성화됨" if settings.ENABLE_METASHAPE_ENGINE else "GPU 처리 엔진 비활성",
            "queue_name": PROCESSING_QUEUE,
        },
        "odm": {
            "enabled": settings.ENABLE_ODM_ENGINE,
            "reason": "활성화됨 (ODM)" if settings.ENABLE_ODM_ENGINE else "4차 스프린트 정책상 비활성",
            "queue_name": "odm",
        },
        "external": {
            "enabled": settings.ENABLE_EXTERNAL_ENGINE,
            "reason": "활성화됨 (External API)" if settings.ENABLE_EXTERNAL_ENGINE else "4차 스프린트 정책상 비활성",
            "queue_name": "external",
        },
    }


def _get_supported_processing_engines() -> set[str]:
    return {
        name
        for name, policy in _get_processing_engine_policies().items()
        if policy.get("enabled")
    }


def _get_default_processing_engine() -> str | None:
    policies = _get_processing_engine_policies()
    for name in [DEFAULT_PROCESSING_ENGINE, "odm", "external"]:
        if policies.get(name, {}).get("enabled"):
            return name
    return None


def _get_queue_name(engine_name: str) -> str:
    policies = _get_processing_engine_policies()
    queue_name = policies.get(engine_name, {}).get("queue_name")
    if queue_name:
        return queue_name
    return PROCESSING_QUEUE


def _metadata_path_for_project(project_id: UUID) -> Path:
    return processing_metadata_path(project_id)


def _count_metadata_reference_rows(metadata_path: Path) -> int:
    try:
        with open(metadata_path, "r", encoding="utf-8", errors="ignore") as f:
            return sum(
                1 for line in f
                if line.strip() and not line.lstrip().startswith("#")
            )
    except OSError:
        return 0


async def _count_project_eo_records(
    db: AsyncSession,
    project_id: UUID,
    completed_only: bool = False,
) -> int:
    query = (
        select(func.count(ExteriorOrientation.id))
        .join(Image, ExteriorOrientation.image_id == Image.id)
        .where(Image.project_id == project_id)
    )
    if completed_only:
        query = query.where(Image.upload_status == "completed")
    result = await db.execute(query)
    return result.scalar() or 0


async def _ensure_eo_ready_for_eo_only_processing(
    db: AsyncSession,
    project_id: UUID,
    completed_only: bool = False,
) -> None:
    eo_count = await _count_project_eo_records(db, project_id, completed_only=completed_only)
    if eo_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "eo_required",
                "message": "처리에 필요한 이미지와 EO 매칭 정보가 없습니다.",
                "confirm_message": "이미지와 EO 파일을 다시 업로드한 뒤 처리해주세요.",
            },
        )

    metadata_path = _metadata_path_for_project(project_id)
    if not metadata_path.exists():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "eo_metadata_missing",
                "message": "처리에 필요한 이미지와 EO 매칭 정보를 다시 확인해야 합니다.",
                "metadata_path": str(metadata_path),
                "confirm_message": "이미지와 EO 파일을 다시 업로드한 뒤 처리해주세요.",
            },
        )
    metadata_count = _count_metadata_reference_rows(metadata_path)
    if metadata_count == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "eo_metadata_empty",
                "message": "처리에 사용할 EO 매칭 정보가 비어 있습니다.",
                "metadata_path": str(metadata_path),
                "confirm_message": "EO 위치 preview의 제외 상태를 확인하거나 이미지와 EO 파일을 다시 업로드해주세요.",
            },
        )
    if metadata_count < eo_count:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "eo_metadata_stale",
                "message": "이미지와 EO 매칭 정보가 현재 업로드 상태와 맞지 않습니다.",
                "eo_count": eo_count,
                "metadata_count": metadata_count,
                "metadata_path": str(metadata_path),
                "confirm_message": "이미지와 EO 파일을 다시 업로드한 뒤 처리해주세요.",
            },
        )

def _uuid_or_none(value: object) -> UUID | None:
    if not value:
        return None
    try:
        return UUID(str(value))
    except Exception:
        return None


def _active_task_for_project(project_id: UUID, force_refresh: bool = False) -> dict | None:
    return get_active_processing_tasks(force_refresh=force_refresh).get(str(project_id))


def _caller_label(user: User) -> str:
    return (
        str(getattr(user, "email", None) or "")
        or str(getattr(user, "username", None) or "")
        or str(getattr(user, "id", "unknown"))
    )


async def _sync_completed_job_result_path(
    db: AsyncSession,
    project: Project,
    job: ProcessingJob,
    active_task: dict | None,
) -> bool:
    """Keep completed status responses aligned with the project's current COG key."""
    if active_task:
        return False
    if not project.ortho_path:
        return False
    if job.status != "completed" and project.status != "completed":
        return False
    if job.result_path == project.ortho_path:
        return False

    job.result_path = project.ortho_path
    await db.commit()
    await db.refresh(project)
    await db.refresh(job)
    return True


async def _select_status_job(
    db: AsyncSession,
    project_id: UUID,
    active_task: dict | None = None,
) -> ProcessingJob | None:
    active_job_id = _uuid_or_none((active_task or {}).get("job_id"))
    if active_job_id:
        result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.id == active_job_id,
                ProcessingJob.project_id == project_id,
            )
        )
        active_job = result.scalar_one_or_none()
        if active_job:
            return active_job

    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(
            case(
                (ProcessingJob.status.in_(["processing", "queued", "scheduled"]), 0),
                else_=1,
            ),
            ProcessingJob.started_at.desc().nullslast(),
            ProcessingJob.completed_at.desc().nullslast(),
        )
        .limit(1)
    )
    return result.scalars().first()


async def _build_processing_status_response(
    db: AsyncSession,
    project: Project,
    job: ProcessingJob,
    active_task: dict | None = None,
) -> ProcessingJobResponse:
    project_id = job.project_id
    status_payload = _read_processing_status_file(project_id)
    step_status = _read_step_status_file(str(project_id))
    runtime_progress = progress_from_step_status(step_status, job.progress or project.progress or 0)
    step_message = infer_message_from_step_status(step_status)
    active_task = active_task or _active_task_for_project(project_id)

    if job.status in TERMINAL_PROCESSING_STATUSES or project.status in TERMINAL_PROCESSING_STATUSES:
        active_task = None

    if active_task:
        changed = False
        if job.status != "processing":
            job.status = "processing"
            changed = True
        if project.status != "processing":
            project.status = "processing"
            changed = True
        if job.started_at is None:
            job.started_at = datetime.utcnow()
            changed = True
        if job.completed_at is not None:
            job.completed_at = None
            changed = True
        if job.error_message:
            job.error_message = None
            changed = True
        if project.progress != runtime_progress:
            project.progress = runtime_progress
            changed = True
        if job.progress != runtime_progress:
            job.progress = runtime_progress
            changed = True
        if changed:
            await db.commit()
            await db.refresh(project)
            await db.refresh(job)
    elif job.status in ("queued", "processing") and status_payload.get("status") in TERMINAL_PROCESSING_STATUSES:
        terminal_status = str(status_payload.get("status"))
        terminal_message = status_payload.get("message") or job.error_message
        job.status = terminal_status
        project.status = terminal_status
        job.progress = runtime_progress
        project.progress = runtime_progress
        if terminal_message:
            job.error_message = terminal_message
        if job.completed_at is None:
            job.completed_at = datetime.utcnow()
        await db.commit()
        await db.refresh(project)
        await db.refresh(job)
    elif job.status in ("queued", "processing") and _celery_task_state(job.celery_task_id) == "REVOKED":
        runtime_progress = _mark_job_cancelled(
            project,
            job,
            progress=runtime_progress,
            message=CANCELLED_PROCESSING_MESSAGE,
        )
        clear_active_processing_task_cache()
        await db.commit()
        await db.refresh(project)
        await db.refresh(job)

    await _sync_completed_job_result_path(db, project, job, active_task)

    response = ProcessingJobResponse.model_validate(job)
    if active_task:
        response.status = "processing"
        response.progress = runtime_progress
        response.error_message = None
    elif job.status in ("queued", "processing"):
        response.progress = runtime_progress

    payload_status = status_payload.get("status")
    fallback_message = status_payload.get("message")
    if job.status in TERMINAL_PROCESSING_STATUSES and payload_status != job.status:
        fallback_message = None
    if job.status in TERMINAL_PROCESSING_STATUSES and not active_task:
        response.message = fallback_message or job.error_message
        if job.status == "cancelled" and not response.message:
            response.message = CANCELLED_PROCESSING_MESSAGE
    elif active_task or job.status in ("queued", "processing"):
        response.message = step_message or fallback_message or response.message
    else:
        response.message = fallback_message or response.message

    if isinstance(status_payload.get("metrics"), dict):
        response.metrics = status_payload.get("metrics")
    if step_status:
        response.step_status = step_status
    processing_events = _read_processing_events(str(project_id))
    if processing_events:
        response.processing_events = processing_events
    if job.status in RESTART_CHOICE_STATUSES and project.status in RESTART_CHOICE_STATUSES:
        checkpoint_summary = _processing_restart_summary(project_id)
        response.restart_choice_required = True
        response.can_resume = checkpoint_summary["can_resume"]
        response.completed_steps = checkpoint_summary["completed_steps"]
        response.failed_step = checkpoint_summary["failed_step"]
        response.next_step = checkpoint_summary["next_step"]
    return response


def _to_float(value):
    """Parse numeric values safely to float."""
    if isinstance(value, int | float):
        if math.isfinite(value):
            return float(value)
    return None


def _percentile(values, ratio: float) -> float | None:
    """Return percentile for a list of numeric values."""
    if not values:
        return None

    sorted_values = sorted(values)
    n = len(sorted_values)

    if n == 1:
        return round(sorted_values[0], 2)

    position = (n - 1) * ratio
    lower = int(math.floor(position))
    upper = int(math.ceil(position))

    if lower == upper:
        return round(sorted_values[int(position)], 2)

    weight = position - lower
    interpolated = sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
    return round(interpolated, 2)


def _safe_rate(count: int, total: int) -> float | None:
    """Return ratio as percentage, safely."""
    if total <= 0:
        return None
    return round((count / total) * 100, 2)

# WebSocket connection manager
class ConnectionManager:
    def __init__(self):
        self.active_connections: dict[str, list[WebSocket]] = {}
    
    async def connect(self, project_id: str, websocket: WebSocket):
        await websocket.accept()
        if project_id not in self.active_connections:
            self.active_connections[project_id] = []
        self.active_connections[project_id].append(websocket)
    
    def disconnect(self, project_id: str, websocket: WebSocket):
        if project_id in self.active_connections:
            try:
                self.active_connections[project_id].remove(websocket)
            except ValueError:
                pass

    async def broadcast(self, project_id: str, message: dict):
        if project_id not in self.active_connections:
            return
        dead = []
        for connection in self.active_connections[project_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead.append(connection)
        for conn in dead:
            try:
                self.active_connections[project_id].remove(conn)
            except ValueError:
                pass

manager = ConnectionManager()


def _require_internal_token(
    internal_token: str,
    query_token: str,
    *,
    expected_scope: str,
) -> None:
    token = internal_token or query_token
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing internal processing token",
        )
    verify_internal_token(token, required_scope=expected_scope)


def _safe_uuid(value: str) -> UUID:
    try:
        return UUID(str(value))
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid project UUID",
        )


async def _get_scoped_project(
    project_id: UUID,
    current_user: User,
    db: AsyncSession,
):
    query = select(Project).where(Project.id == project_id)
    if not is_admin_role(current_user.role):
        query = query.where(Project.organization_id == current_user.organization_id)
    result = await db.execute(query)
    return result.scalar_one_or_none()


def _apply_project_access_scope(query, current_user: User):
    if is_admin_role(current_user.role):
        return query

    if current_user.organization_id is not None:
        return query.where(Project.organization_id == current_user.organization_id)

    return query.where(Project.owner_id == current_user.id)


@router.get("/engines", response_model=ProcessingEnginesResponse)
async def get_processing_engines(current_user: User = Depends(get_current_user)):
    policies = _get_processing_engine_policies()
    return ProcessingEnginesResponse(
        engines=[
            ProcessingEnginePolicy(
                name=name,
                enabled=policy["enabled"],
                reason=policy["reason"],
                queue_name=policy.get("queue_name"),
            )
            for name, policy in sorted(policies.items())
        ],
        default_engine=_get_default_processing_engine() or DEFAULT_PROCESSING_ENGINE,
    )


@router.post("/projects/{project_id}/start", response_model=ProcessingJobResponse)
async def start_processing(
    project_id: UUID,
    options: ProcessingOptions,
    force: bool = False,
    force_restart: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start orthophoto generation processing.

    Submits a job to the selected processing engine.

    Args:
        force: If True, proceed with only completed images even if some uploads are incomplete/failed.
        force_restart: If True, cancel existing job and start a new one.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    project = await _get_scoped_project(project_id, current_user, db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    if force_restart:
        print(
            "[processing.force_restart] requested "
            f"caller={_caller_label(current_user)} project_id={project_id}"
        )

    supported_engines = _get_supported_processing_engines()
    if not supported_engines:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="현재 사용할 수 있는 처리 엔진이 없습니다. 서버 환경 변수를 확인하세요.",
        )

    if options.engine not in supported_engines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "type": "unsupported_engine",
                "message": "지원되지 않는 처리 엔진입니다.",
                "engine": options.engine,
                "supported_engines": sorted(supported_engines),
            },
        )

    active_task = _active_task_for_project(project_id, force_refresh=True)
    if active_task:
        active_job = await _select_status_job(db, project_id, active_task)
        if active_job:
            return await _build_processing_status_response(db, project, active_job, active_task)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "job_already_running",
                "message": "이 프로젝트의 처리 작업이 이미 worker-engine에서 실행 중입니다.",
                "can_force_restart": True,
            },
        )

    # Check image upload status before processing
    from app.models.project import Image
    from sqlalchemy import func
    from datetime import datetime, timedelta

    image_status_result = await db.execute(
        select(
            Image.upload_status,
            func.count(Image.id).label("count")
        )
        .where(Image.project_id == project_id)
        .group_by(Image.upload_status)
    )
    status_counts = {row.upload_status: row.count for row in image_status_result}

    completed_count = status_counts.get("completed", 0)
    uploading_count = status_counts.get("uploading", 0)
    failed_count = status_counts.get("failed", 0)

    if completed_count == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="업로드 완료된 이미지가 없습니다. 이미지를 먼저 업로드해주세요.",
        )

    # 문제 있는 이미지 처리 로직
    incomplete_count = 0
    incomplete_reason = ""

    if uploading_count > 0:
        # 오래된 uploading 이미지 확인 (1시간 이상)
        stale_threshold = datetime.utcnow() - timedelta(hours=1)
        stale_result = await db.execute(
            select(func.count(Image.id)).where(
                Image.project_id == project_id,
                Image.upload_status == "uploading",
                Image.created_at < stale_threshold,
            )
        )
        stale_count = stale_result.scalar() or 0
        recent_count = uploading_count - stale_count

        if recent_count > 0:
            # 최근 업로드 중인 이미지가 있음 - 무조건 대기 필요
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"현재 업로드 중인 이미지가 {uploading_count}개 있습니다. "
                       f"업로드가 완료된 후 다시 시도해주세요. "
                       f"업로드 중 브라우저를 닫거나 페이지를 이동하면 업로드가 중단될 수 있습니다.",
            )
        elif stale_count > 0:
            # 모두 오래된 이미지 - 업로드 중단으로 판단, 사용자 확인 후 진행 가능
            incomplete_count += stale_count
            incomplete_reason = f"업로드가 중단된 이미지 {stale_count}개"

    if failed_count > 0:
        if incomplete_reason:
            incomplete_reason += f", 업로드 실패 이미지 {failed_count}개"
        else:
            incomplete_reason = f"업로드 실패한 이미지 {failed_count}개"
        incomplete_count += failed_count

    # 문제가 있는 이미지가 있고, force가 아닌 경우 확인 요청
    if incomplete_count > 0 and not force:
        total_images = completed_count + incomplete_count
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "incomplete_uploads",
                "message": f"전체 {total_images}개 이미지 중 {incomplete_reason}가 있습니다.",
                "completed_count": completed_count,
                "incomplete_count": incomplete_count,
                "confirm_message": f"완료된 {completed_count}개 이미지만으로 처리를 진행하시겠습니까?",
            },
        )

    if options.eo_only_align:
        await _ensure_eo_ready_for_eo_only_processing(
            db,
            project_id,
            completed_only=True,
        )

    # Check if there's already a running job
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status.in_(["queued", "processing"]),
        )
    )
    existing_job = result.scalar_one_or_none()
    if existing_job:
        now = datetime.utcnow()
        is_stale = False
        stale_reason = ""
        status_payload = _read_processing_status_file(project_id)
        status_payload_value = status_payload.get("status")

        if status_payload_value in TERMINAL_PROCESSING_STATUSES:
            is_stale = True
            stale_reason = f"처리 상태 파일이 {status_payload_value} 상태입니다"

        # Case 1: Job never started and has been queued for more than 6 hours
        elif existing_job.started_at is None:
            is_stale = True
            stale_reason = "작업이 시작되지 않고 대기 중이었습니다"

        # Case 2: Job started more than 24 hours ago
        elif (now - existing_job.started_at) > timedelta(hours=24):
            is_stale = True
            stale_reason = "작업이 24시간 이상 진행 중이었습니다"

        # Case 3: User requested force restart
        if force_restart:
            is_stale = True
            stale_reason = "사용자가 강제 재시작을 요청했습니다"
            print(
                "[processing.force_restart] accepted for non-active queued/processing job "
                f"caller={_caller_label(current_user)} project_id={project_id} "
                f"existing_job_id={existing_job.id} stale_reason={stale_reason}"
            )

            # Also revoke the Celery task if exists
            if existing_job.celery_task_id:
                try:
                    from app.workers.tasks import celery_app
                    celery_app.control.revoke(existing_job.celery_task_id, terminate=True)
                    _remove_queued_celery_message(
                        existing_job.celery_task_id,
                        _get_queue_name(existing_job.engine or DEFAULT_PROCESSING_ENGINE),
                    )
                except Exception:
                    pass

        if is_stale:
            # Auto-reset stale job
            existing_job.status = "failed"
            existing_job.error_message = f"작업이 자동 초기화되었습니다: {stale_reason}"
            await db.commit()
        else:
            # Return detailed error for frontend to handle
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "type": "job_already_running",
                    "message": "이 프로젝트에 이미 진행 중인 처리 작업이 있습니다",
                    "job_id": str(existing_job.id),
                    "job_status": existing_job.status,
                    "started_at": existing_job.started_at.isoformat() if existing_job.started_at else None,
                    "progress": existing_job.progress,
                    "can_force_restart": True
                },
            )

    latest_job = await _select_status_job(db, project_id, None)
    if (
        latest_job
        and latest_job.status in RESTART_CHOICE_STATUSES
        and project.status in RESTART_CHOICE_STATUSES
        and not force_restart
    ):
        checkpoint_summary = _processing_restart_summary(project_id)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "restart_choice_required",
                "message": "이전 처리 작업이 완료되지 않았습니다. 처리 방식을 선택해주세요.",
                "job_id": str(latest_job.id),
                "job_status": latest_job.status,
                "project_status": project.status,
                "progress": latest_job.progress or project.progress or 0,
                "can_resume": checkpoint_summary["can_resume"],
                "completed_steps": checkpoint_summary["completed_steps"],
                "failed_step": checkpoint_summary["failed_step"],
                "next_step": checkpoint_summary["next_step"],
                "confirm_message": (
                    "완료된 단계부터 이어서 처리하거나, 기존 체크포인트를 버리고 처음부터 새로 처리할 수 있습니다."
                    if checkpoint_summary["can_resume"]
                    else "재사용 가능한 완료 단계가 없어 처음부터 새로 처리해야 합니다."
                ),
            },
        )

    if force_restart and latest_job and latest_job.status == "completed":
        await _sync_completed_job_result_path(db, project, latest_job, None)
        print(
            "[processing.force_restart] rejected for completed latest job without active worker task "
            f"caller={_caller_label(current_user)} project_id={project_id} "
            f"existing_job_id={latest_job.id} stale_reason=latest_job_completed_no_active_task"
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "type": "completed_job_restart_requires_explicit_action",
                "message": "이미 완료된 프로젝트입니다. 자동 재시작 요청은 차단되었습니다.",
                "job_id": str(latest_job.id),
                "job_status": latest_job.status,
                "result_path": latest_job.result_path,
                "can_force_restart": False,
                "confirm_message": "완료된 프로젝트는 기존 결과를 유지한 채 새 처리 작업으로 다시 시작할 수 있습니다.",
            },
        )
    
    
    # Create processing job
    job = ProcessingJob(
        project_id=project_id,
        engine=options.engine,
        gsd=options.gsd,
        output_crs=options.output_crs,
        output_format=options.output_format,
        status="queued",
        process_mode=options.process_mode,  # 처리 모드 저장
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    
    # Update project status
    project.status = "queued"
    project.progress = 0
    
    # Commit DB changes BEFORE submitting to Celery (prevents race condition
    # where worker picks up the task before the transaction is committed)
    await db.commit()

    from app.workers.tasks import process_orthophoto

    queue_name = _get_queue_name(options.engine)

    try:
        task = process_orthophoto.apply_async(
            args=[str(job.id), str(project_id), options.model_dump()],
            queue=queue_name,
        )
        # Store celery task ID (non-critical)
        job.celery_task_id = task.id
        await db.commit()
    except Exception:
        # Celery submission failed — revert DB state
        job.status = "error"
        job.error_message = "태스크 큐 전송 실패"
        project.status = "error"
        await db.commit()
        raise
    
    return ProcessingJobResponse.model_validate(job)


@router.post("/projects/{project_id}/schedule", response_model=ProcessingJobResponse)
async def schedule_processing(
    project_id: UUID,
    options: ProcessingOptions,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Schedule processing to start automatically when all uploads complete.

    Creates a ProcessingJob with status="scheduled". The actual processing
    will be triggered by the upload completion hook when all images are uploaded.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    project = await _get_scoped_project(project_id, current_user, db)
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Validate engine
    supported_engines = _get_supported_processing_engines()
    if not supported_engines:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="현재 사용할 수 있는 처리 엔진이 없습니다.",
        )

    if options.engine not in supported_engines:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"지원되지 않는 처리 엔진: {options.engine}",
        )

    if options.eo_only_align:
        await _ensure_eo_ready_for_eo_only_processing(
            db,
            project_id,
            completed_only=False,
        )

    # Check for existing active/scheduled jobs
    result = await db.execute(
        select(ProcessingJob).where(
            ProcessingJob.project_id == project_id,
            ProcessingJob.status.in_(["queued", "processing", "scheduled"]),
        )
    )
    existing_job = result.scalar_one_or_none()
    if existing_job:
        if existing_job.status == "scheduled":
            # Update existing scheduled job with new options
            existing_job.engine = options.engine
            existing_job.gsd = options.gsd
            existing_job.output_crs = options.output_crs
            existing_job.output_format = options.output_format
            existing_job.process_mode = options.process_mode
            await db.commit()
            await db.refresh(existing_job)
            return ProcessingJobResponse.model_validate(existing_job)
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="이 프로젝트에 이미 진행 중인 처리 작업이 있습니다.",
            )

    # Create scheduled processing job
    job = ProcessingJob(
        project_id=project_id,
        engine=options.engine,
        gsd=options.gsd,
        output_crs=options.output_crs,
        output_format=options.output_format,
        status="scheduled",
        process_mode=options.process_mode,
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)

    # Update project status
    project.status = "scheduled"

    # Check if all images are already uploaded — if so, transition immediately
    from app.models.project import Image
    from sqlalchemy import func

    status_result = await db.execute(
        select(
            Image.upload_status,
            func.count(Image.id).label("cnt"),
        )
        .where(Image.project_id == project_id)
        .group_by(Image.upload_status)
    )
    status_counts = {row.upload_status: row.cnt for row in status_result}
    pending_or_uploading = status_counts.get("pending", 0) + status_counts.get("uploading", 0)
    completed_images = status_counts.get("completed", 0)

    if pending_or_uploading == 0 and completed_images > 0:
        # All images already uploaded — transition to queued and submit task
        job.status = "queued"
        project.status = "queued"
        project.progress = 0

        await db.commit()

        try:
            from app.workers.tasks import process_orthophoto
            options_dict = {
                "engine": job.engine,
                "gsd": job.gsd,
                "output_crs": job.output_crs,
                "output_format": job.output_format,
                "process_mode": job.process_mode or "Normal",
                "eo_only_align": options.eo_only_align,
                "build_point_cloud": options.build_point_cloud,
            }
            queue_name = _get_queue_name(job.engine or DEFAULT_PROCESSING_ENGINE)
            task = process_orthophoto.apply_async(
                args=[str(job.id), str(project_id), options_dict],
                queue=queue_name,
            )
            job.celery_task_id = task.id
            await db.commit()
        except Exception as celery_err:
            # Celery submission failed — revert to scheduled
            job.status = "scheduled"
            project.status = "scheduled"
            await db.commit()
    else:
        await db.commit()

    await db.refresh(job)
    return ProcessingJobResponse.model_validate(job)

@router.get("/projects/{project_id}/status", response_model=ProcessingJobResponse)
async def get_processing_status(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the latest processing job status for a project."""
    # Check permission
    permission_checker = PermissionChecker("view")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    active_task = _active_task_for_project(project_id)
    job = await _select_status_job(db, project_id, active_task)
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No processing job found for this project",
        )
    
    return await _build_processing_status_response(db, scoped_project, job, active_task)


@router.post("/projects/{project_id}/cancel")
async def cancel_processing(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Cancel a running processing job."""
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    active_task = _active_task_for_project(project_id, force_refresh=True)
    if active_task:
        job = await _select_status_job(db, project_id, active_task)
    else:
        result = await db.execute(
            select(ProcessingJob).where(
                ProcessingJob.project_id == project_id,
                ProcessingJob.status.in_(["queued", "processing"]),
            )
        )
        job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No running job found",
        )
    
    # Revoke Celery task
    celery_task_id = job.celery_task_id or (active_task or {}).get("task_id")
    if celery_task_id:
        from app.workers.tasks import celery_app
        celery_app.control.revoke(celery_task_id, terminate=True)
        _remove_queued_celery_message(
            celery_task_id,
            _get_queue_name(job.engine or DEFAULT_PROCESSING_ENGINE),
        )
    clear_active_processing_task_cache()

    progress = _mark_job_cancelled(
        scoped_project,
        job,
        progress=job.progress or scoped_project.progress or 0,
        message=CANCELLED_PROCESSING_MESSAGE,
    )
    
    await db.commit()
    await manager.broadcast(
        str(project_id),
        {
            "status": "cancelled",
            "progress": progress,
            "message": CANCELLED_PROCESSING_MESSAGE,
        },
    )
    
    return {
        "message": CANCELLED_PROCESSING_MESSAGE,
        "status": "cancelled",
        "progress": progress,
        "project_id": str(project_id),
        "job_id": str(job.id),
    }


@router.get("/jobs", response_model=list[ProcessingJobResponse])
async def list_processing_jobs(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List all processing jobs for the current user's projects."""
    # Get jobs for user's projects
    query = (
        select(ProcessingJob)
        .join(Project)
        .order_by(ProcessingJob.started_at.desc().nullslast())
    )
    
    query = _apply_project_access_scope(query, current_user)
    
    result = await db.execute(query.limit(50))
    jobs = result.scalars().all()
    
    responses = []
    for job in jobs:
        status_payload = _read_processing_status_file(job.project_id)
        response = ProcessingJobResponse.model_validate(job)
        if status_payload.get("message"):
            response.message = status_payload.get("message")
        if isinstance(status_payload.get("metrics"), dict):
            response.metrics = status_payload.get("metrics")
        responses.append(response)
    return responses


@router.get("/metrics", response_model=ProcessingMetricsResponse)
async def get_processing_metrics(
    limit: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get processing queue/throughput metrics for the scoped user."""
    query = (
        select(ProcessingJob, Project.title)
        .join(Project)
        .order_by(ProcessingJob.started_at.desc().nullslast())
    )
    query = _apply_project_access_scope(query, current_user)

    result = await db.execute(query.limit(limit))
    rows = result.all()

    jobs = [row[0] for row in rows]
    project_titles = {row[0].project_id: row[1] for row in rows}

    status_counts = Counter({status: 0 for status in ["queued", "processing", "completed", "error", "failed", "cancelled"]})

    queue_wait_values = []
    total_elapsed_values = []
    memory_usage_values = []
    queue_wait_violation_count = 0
    total_elapsed_violation_count = 0
    memory_violation_count = 0

    recent_jobs = []
    for job in jobs:
        status_counts[job.status] = status_counts.get(job.status, 0) + 1
        status_payload = _read_processing_status_file(job.project_id)
        metrics = status_payload.get("metrics") if isinstance(status_payload.get("metrics"), dict) else {}

        queue_wait_seconds = _to_float(metrics.get("queue_wait_seconds"))
        total_elapsed_seconds = _to_float(metrics.get("total_elapsed_seconds"))
        memory_usage_mb = _to_float(metrics.get("memory_usage_mb"))

        slo = metrics.get("slo") if isinstance(metrics.get("slo"), dict) else {}
        queue_wait_warn_seconds = _to_float(slo.get("queue_wait_warn_seconds"))
        total_elapsed_warn_seconds = _to_float(slo.get("total_elapsed_warn_seconds"))
        memory_warn_mb = _to_float(slo.get("memory_warn_mb"))

        queue_wait_exceeded = bool(queue_wait_seconds is not None and queue_wait_warn_seconds is not None and queue_wait_seconds > queue_wait_warn_seconds)
        total_elapsed_exceeded = bool(total_elapsed_seconds is not None and total_elapsed_warn_seconds is not None and total_elapsed_seconds > total_elapsed_warn_seconds)
        memory_exceeded = bool(memory_usage_mb is not None and memory_warn_mb is not None and memory_usage_mb > memory_warn_mb)

        if metrics.get("slo", {}).get("queue_wait_exceeded", False):
            queue_wait_exceeded = True
        if metrics.get("slo", {}).get("total_elapsed_exceeded", False):
            total_elapsed_exceeded = True
        if metrics.get("slo", {}).get("memory_exceeded", False):
            memory_exceeded = True

        if queue_wait_exceeded:
            queue_wait_violation_count += 1
        if total_elapsed_exceeded:
            total_elapsed_violation_count += 1
        if memory_exceeded:
            memory_violation_count += 1

        if queue_wait_seconds is not None:
            queue_wait_values.append(queue_wait_seconds)
        if total_elapsed_seconds is not None:
            total_elapsed_values.append(total_elapsed_seconds)
        if memory_usage_mb is not None:
            memory_usage_values.append(memory_usage_mb)

        recent_jobs.append(
            ProcessingMetricJobSummary(
                project_id=job.project_id,
                project_title=project_titles.get(job.project_id),
                engine=job.engine,
                status=job.status,
                progress=job.progress or 0,
                queue_wait_seconds=queue_wait_seconds,
                total_elapsed_seconds=total_elapsed_seconds,
                memory_usage_mb=memory_usage_mb,
                queue_wait_warn_seconds=queue_wait_warn_seconds,
                total_elapsed_warn_seconds=total_elapsed_warn_seconds,
                memory_warn_mb=memory_warn_mb,
                queue_wait_exceeded=queue_wait_exceeded,
                total_elapsed_exceeded=total_elapsed_exceeded,
                memory_exceeded=memory_exceeded,
            )
        )

    queue_wait_sample_count = len(queue_wait_values)
    total_elapsed_sample_count = len(total_elapsed_values)
    memory_usage_sample_count = len(memory_usage_values)

    return ProcessingMetricsResponse(
        generated_at=datetime.utcnow(),
        scope="admin" if is_admin_role(current_user.role) else "organization",
        organization_id=current_user.organization_id if not is_admin_role(current_user.role) else None,
        total_jobs=len(jobs),
        status_counts=dict(status_counts),
        summary=ProcessingMetricsSummary(
            queue_wait_sample_count=queue_wait_sample_count,
            queue_wait_avg_seconds=round(sum(queue_wait_values) / queue_wait_sample_count, 2) if queue_wait_sample_count else None,
            queue_wait_p95_seconds=_percentile(queue_wait_values, 0.95),
            queue_wait_violation_count=queue_wait_violation_count,
            queue_wait_violation_rate=_safe_rate(queue_wait_violation_count, queue_wait_sample_count),
            total_elapsed_sample_count=total_elapsed_sample_count,
            total_elapsed_avg_seconds=round(sum(total_elapsed_values) / total_elapsed_sample_count, 2) if total_elapsed_sample_count else None,
            total_elapsed_p95_seconds=_percentile(total_elapsed_values, 0.95),
            total_elapsed_violation_count=total_elapsed_violation_count,
            total_elapsed_violation_rate=_safe_rate(total_elapsed_violation_count, total_elapsed_sample_count),
            memory_usage_sample_count=memory_usage_sample_count,
            memory_usage_avg_mb=round(sum(memory_usage_values) / memory_usage_sample_count, 2) if memory_usage_sample_count else None,
            memory_usage_p95_mb=_percentile(memory_usage_values, 0.95),
            memory_violation_count=memory_violation_count,
            memory_violation_rate=_safe_rate(memory_violation_count, memory_usage_sample_count),
        ),
        recent_jobs=recent_jobs,
    )


# WebSocket endpoint for real-time status updates
@router.websocket("/ws/projects/{project_id}/status")
async def websocket_status(
    websocket: WebSocket,
    project_id: str,
    db: AsyncSession = Depends(get_db),
):
    """
    WebSocket endpoint for real-time processing status updates.
    
    Clients connect to this endpoint to receive live progress updates.
    Requires a valid JWT token via:
      - query parameter `token`
      - or Authorization header in the websocket handshake.
    """
    token = websocket.query_params.get("token")
    if not token:
        auth_header = websocket.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            token = auth_header.split(" ", 1)[1]

    if not token:
        await websocket.close(code=1008)
        return

    try:
        payload = verify_token(token, "access")
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing user id")
        user_result = await db.execute(select(User).where(User.id == user_id))
        current_user = user_result.scalar_one_or_none()
        if not current_user:
            raise ValueError("User not found")

        scoped_project = await _get_scoped_project(_safe_uuid(project_id), current_user, db)
        if not scoped_project:
            await websocket.close(code=1008)
            return

        permission_checker = PermissionChecker("view")
        if not await permission_checker.check(project_id, current_user, db):
            await websocket.close(code=1008)
            return
    except Exception:
        await websocket.close(code=1008)
        return

    await manager.connect(project_id, websocket)
    # Send latest known status immediately on connect
    try:
        project_uuid = _safe_uuid(project_id)
        active_task = _active_task_for_project(project_uuid)
        job = await _select_status_job(db, project_uuid, active_task)
        if job:
            response = await _build_processing_status_response(db, scoped_project, job, active_task)
            payload = response.model_dump(mode="json")
            payload["project_id"] = project_id
            payload["type"] = "progress" if response.status == "processing" else response.status
            await websocket.send_json(payload)
    except Exception:
        pass
    try:
        while True:
            # Keep connection alive, actual updates come from Celery worker
            data = await websocket.receive_text()
            # Echo back for ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except (WebSocketDisconnect, Exception):
        manager.disconnect(project_id, websocket)


# REST endpoint for Celery workers to trigger WebSocket broadcasts
from pydantic import BaseModel

class BroadcastRequest(BaseModel):
    project_id: str
    status: str
    progress: int
    message: str = None

@router.post("/broadcast")
async def broadcast_update(
    request: BroadcastRequest,
    x_internal_token: str = Header(default=None, alias="X-Internal-Token"),
    token: str = Query(default=None),
):
    """Internal endpoint for Celery workers or external engines to trigger WebSocket broadcasts."""
    _require_internal_token(
        internal_token=x_internal_token,
        query_token=token,
        expected_scope="processing_broadcast",
    )

    await manager.broadcast(request.project_id, {
        "project_id": request.project_id,
        "status": request.status,
        "progress": request.progress,
        "message": request.message,
        "type": "progress" if request.status == "processing" else request.status,
    })
    return {"status": "broadcast_sent"}


@router.post("/webhook")
async def external_processing_webhook(
    request: BroadcastRequest,
    x_internal_token: str = Header(default=None, alias="X-Internal-Token"),
    token: str = Query(default=None, alias="internal_token"),
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook endpoint for external processing engines to report status.
    """
    _require_internal_token(
        internal_token=x_internal_token,
        query_token=token,
        expected_scope="processing_webhook",
    )

    project_uuid = _safe_uuid(request.project_id)

    # 1. Update Job and Project status in DB
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_uuid)
        .order_by(ProcessingJob.started_at.desc().nullslast())
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.status = request.status
    job.progress = request.progress
    if request.status == "completed":
        job.completed_at = datetime.utcnow()
    elif request.status == "failed":
        job.error_message = request.message
        
    # Update project
    proj_result = await db.execute(select(Project).where(Project.id == project_uuid))
    project = proj_result.scalar_one_or_none()
    if project:
        project.status = request.status
        project.progress = request.progress

    await db.commit()

    # 2. Broadcast via WebSocket
    await manager.broadcast(request.project_id, {
        "project_id": request.project_id,
        "status": request.status,
        "progress": request.progress,
        "message": request.message,
        "type": "progress" if request.status == "processing" else request.status,
    })

    return {"status": "received"}


# Function to be called by Celery worker to broadcast updates
async def broadcast_status_update(project_id: str, status: str, progress: int, message: str = None):
    """Broadcast status update to all connected WebSocket clients."""
    await manager.broadcast(project_id, {
        "project_id": project_id,
        "status": status,
        "progress": progress,
        "message": message,
    })
