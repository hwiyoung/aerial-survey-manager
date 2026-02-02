"""Processing API endpoints."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json
from pathlib import Path

from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob
from app.schemas.project import ProcessingOptions, ProcessingJobResponse
from app.auth.jwt import get_current_user, PermissionChecker

router = APIRouter(prefix="/processing", tags=["Processing"])


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


@router.post("/projects/{project_id}/start", response_model=ProcessingJobResponse)
async def start_processing(
    project_id: UUID,
    options: ProcessingOptions,
    force: bool = False,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start orthophoto generation processing.

    Submits a job to the selected processing engine (ODM or external).

    Args:
        force: If True, proceed with only completed images even if some uploads are incomplete/failed.
    """
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    # Check project exists
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
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
        # Check if job is stale (started more than 24 hours ago or never started)
        from datetime import timedelta
        is_stale = (
            existing_job.started_at is None or
            (datetime.utcnow() - existing_job.started_at) > timedelta(hours=24)
        )
        
        if is_stale:
            # Auto-reset stale job
            existing_job.status = "failed"
            existing_job.error_message = "Job was stale and auto-reset"
            await db.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A processing job is already running for this project",
            )
    
    
    # Create processing job
    job = ProcessingJob(
        project_id=project_id,
        engine=options.engine,
        gsd=options.gsd,
        output_crs=options.output_crs,
        output_format=options.output_format,
        status="queued",
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    
    # Update project status
    project.status = "queued"
    project.progress = 0
    
    # Submit to Celery
    # The queue is selected based on the engine
    from app.workers.tasks import process_orthophoto
    
    if options.engine == "metashape":
        queue_name = "metashape"
    elif options.engine == "odm":
        queue_name = "odm"
    else:
        queue_name = "external"
    
    task = process_orthophoto.apply_async(
        args=[str(job.id), str(project_id), options.model_dump()],
        queue=queue_name,
    )
    
    # Store celery task ID
    job.celery_task_id = task.id
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
    project_result = await db.execute(select(Project).where(Project.id == project_id))
    project = project_result.scalar_one()
    project.status = "cancelled"
    
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
    
    if current_user.role != "admin":
        query = query.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
    
    result = await db.execute(query.limit(50))
    jobs = result.scalars().all()
    
    responses = []
    for job in jobs:
        status_payload = _read_processing_status_file(job.project_id)
        response = ProcessingJobResponse.model_validate(job)
        if status_payload.get("message"):
            response.message = status_payload.get("message")
        responses.append(response)
    return responses


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
    """
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
async def broadcast_update(request: BroadcastRequest):
    """
    Internal endpoint for Celery workers or External Engines to trigger WebSocket broadcasts.
    """
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
    db: AsyncSession = Depends(get_db),
):
    """
    Webhook endpoint for external processing engines to report status.
    """
    # 1. Update Job and Project status in DB
    result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == request.project_id)
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
    proj_result = await db.execute(select(Project).where(Project.id == request.project_id))
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
