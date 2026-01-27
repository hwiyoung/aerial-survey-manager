"""Processing API endpoints."""
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import json

from app.database import get_db
from app.models.user import User
from app.models.project import Project, ProcessingJob
from app.schemas.project import ProcessingOptions, ProcessingJobResponse
from app.auth.jwt import get_current_user, PermissionChecker

router = APIRouter(prefix="/processing", tags=["Processing"])

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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Start orthophoto generation processing.
    
    Submits a job to the selected processing engine (ODM or external).
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
    
    # Submit to Celery (will be implemented in workers/tasks.py)
    # The queue is selected based on the engine
    from app.workers.tasks import process_orthophoto
    queue_name = "odm" if options.engine == "odm" else "external"
    
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
    
    return ProcessingJobResponse.model_validate(job)


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
    
    return [ProcessingJobResponse.model_validate(job) for job in jobs]


# WebSocket endpoint for real-time status updates
@router.websocket("/ws/projects/{project_id}/status")
async def websocket_status(
    websocket: WebSocket,
    project_id: str,
):
    """
    WebSocket endpoint for real-time processing status updates.
    
    Clients connect to this endpoint to receive live progress updates.
    """
    await manager.connect(project_id, websocket)
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
