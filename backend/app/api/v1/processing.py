"""Processing API endpoints."""
import math
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
from sqlalchemy import select
import json
from pathlib import Path

from app.config import get_settings
from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob
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

router = APIRouter(prefix="/processing", tags=["Processing"])
DEFAULT_PROCESSING_ENGINE = "metashape"
PROCESSING_QUEUE = "metashape"


def _get_processing_engine_policies():
    settings = get_settings()
    return {
        "metashape": {
            "enabled": settings.ENABLE_METASHAPE_ENGINE,
            "reason": "활성화됨" if settings.ENABLE_METASHAPE_ENGINE else "ENABLE_METASHAPE_ENGINE=false",
            "queue_name": "metashape",
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


def _read_processing_status_file(project_id: str) -> dict:
    try:
        from app.config import get_settings
        settings = get_settings()
        status_path = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project_id) / "processing_status.json"
        if status_path.exists():
            with open(status_path, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


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
            self.active_connections[project_id].remove(websocket)
    
    async def broadcast(self, project_id: str, message: dict):
        if project_id in self.active_connections:
            for connection in self.active_connections[project_id]:
                try:
                    await connection.send_json(message)
                except Exception:
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

        # Case 1: Job never started and has been queued for more than 6 hours
        if existing_job.started_at is None:
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

            # Also revoke the Celery task if exists
            if existing_job.celery_task_id:
                try:
                    from app.workers.tasks import celery_app
                    celery_app.control.revoke(existing_job.celery_task_id, terminate=True)
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
    
    # Submit to Celery based on selected engine's dedicated queue
    from app.workers.tasks import process_orthophoto

    queue_name = _get_queue_name(options.engine)
    
    task = process_orthophoto.apply_async(
        args=[str(job.id), str(project_id), options.model_dump()],
        queue=queue_name,
    )
    
    # Store celery task ID
    job.celery_task_id = task.id
    await db.commit()
    
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

    await db.commit()

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
    
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project_id)
        .order_by(ProcessingJob.started_at.desc().nullsfirst())
    )
    job = result.scalar_one_or_none()
    
    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No processing job found for this project",
        )
    
    status_payload = _read_processing_status_file(project_id)
    response = ProcessingJobResponse.model_validate(job)
    if status_payload.get("message"):
        response.message = status_payload.get("message")
    if isinstance(status_payload.get("metrics"), dict):
        response.metrics = status_payload.get("metrics")
    return response


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
    if job.celery_task_id:
        from app.workers.tasks import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)
    
    job.status = "cancelled"
    
    # Update project status
    scoped_project.status = "cancelled"
    
    await db.commit()
    
    return {"message": "Processing job cancelled"}


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
        .order_by(ProcessingJob.started_at.desc().nullsfirst())
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
        .order_by(ProcessingJob.started_at.desc().nullsfirst())
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
        result = await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.project_id == project_id)
            .order_by(ProcessingJob.started_at.desc().nullsfirst())
        )
        job = result.scalar_one_or_none()
        if job:
            status_payload = _read_processing_status_file(project_id)
            await websocket.send_json({
                "project_id": project_id,
                "status": job.status,
                "progress": job.progress,
                "message": status_payload.get("message") or (job.error_message if job.status in ("error", "failed") else None),
                "type": "progress" if job.status == "processing" else job.status,
            })
    except Exception:
        pass
    try:
        while True:
            # Keep connection alive, actual updates come from Celery worker
            data = await websocket.receive_text()
            # Echo back for ping/pong
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
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
        .order_by(ProcessingJob.started_at.desc().nullsfirst())
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
