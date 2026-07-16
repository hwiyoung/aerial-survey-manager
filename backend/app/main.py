"""FastAPI application entry point."""
import json
from contextlib import asynccontextmanager
from datetime import datetime
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update, select

from app.config import get_settings
from app.api.v1 import router as api_v1_router
from app.database import async_session
from app.models.project import ProcessingJob, Project
from app.services.processing_lifecycle import startup_recovery_in_grace_period
from app.utils.storage_paths import processing_status_path

settings = get_settings()
CANCELLED_PROCESSING_MESSAGE = "처리가 취소되었습니다."
UNAPPLIED_CRS_CORRECTION_MESSAGE = (
    "좌표계 변경 예약이 최종 산출물에 적용되지 않았습니다. "
    "worker-engine 재시작 후 다시 처리해야 합니다."
)


def _active_processing_job_ids() -> set[str] | None:
    try:
        from app.workers.tasks import celery_app
    except Exception as exc:
        print(f"[startup] Celery active task 확인 실패: {exc}")
        return None

    try:
        inspector = celery_app.control.inspect(timeout=5)
        responding_workers = inspector.ping() or {}
        if not responding_workers:
            return None
        task_snapshots = [
            inspector.active() or {},
            inspector.reserved() or {},
            inspector.scheduled() or {},
        ]
    except Exception as exc:
        print(f"[startup] Celery task 조회 실패: {exc}")
        return None

    active_ids: set[str] = set()
    for tasks_by_worker in task_snapshots:
        for tasks in tasks_by_worker.values():
            for raw_task in tasks or []:
                task = raw_task.get("request", raw_task)
                if task.get("name") != "app.workers.tasks.process_orthophoto":
                    continue
                args = task.get("args") or []
                if isinstance(args, str):
                    try:
                        import ast

                        args = ast.literal_eval(args)
                    except Exception:
                        args = []
                if isinstance(args, (list, tuple)) and args:
                    active_ids.add(str(args[0]))
    return active_ids


def _celery_task_state(task_id: str | None) -> str | None:
    if not task_id:
        return None
    try:
        from app.workers.tasks import celery_app

        return celery_app.AsyncResult(task_id).state
    except Exception as exc:
        print(f"[startup] Celery task 상태 확인 실패 {task_id}: {exc}")
        return None


def _write_cancelled_status_file(job: ProcessingJob) -> None:
    try:
        status_file = processing_status_path(job.project_id)
        status_file.parent.mkdir(parents=True, exist_ok=True)
        with open(status_file, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "job_id": str(job.id),
                    "status": "cancelled",
                    "progress": int(job.progress or 0),
                    "message": CANCELLED_PROCESSING_MESSAGE,
                    "updated_at": datetime.utcnow().isoformat(),
                },
                f,
                ensure_ascii=False,
                indent=2,
            )
    except Exception as exc:
        print(f"[startup] 취소 상태 파일 작성 실패 job_id={job.id}: {exc}")


def _read_processing_status_file(job: ProcessingJob) -> dict:
    try:
        status_file = processing_status_path(job.project_id)
        if not status_file.exists() or not job.started_at:
            return {}
        status_mtime = datetime.fromtimestamp(status_file.stat().st_mtime)
        if status_mtime < job.started_at:
            return {}
        with open(status_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {}
        payload_job_id = data.get("job_id")
        if payload_job_id and str(payload_job_id) != str(job.id):
            return {}
        return data
    except Exception as exc:
        print(f"[startup] 처리 상태 파일 읽기 실패 job_id={job.id}: {exc}")
    return {}


async def _recover_stuck_jobs():
    """서버 재시작(전원 차단 포함) 후 'processing' 상태로 고착된 작업을 복구한다.

    정전/강제 종료 시 Celery 태스크는 소멸하지만 DB 상태는 'processing'으로 남는다.
    이를 방치하면 UI에서 영원히 '처리 중'으로 표시되고 재처리가 불가능해진다.
    """
    async with async_session() as db:
        # 고착된 processing_jobs 조회
        result = await db.execute(
            select(ProcessingJob).where(ProcessingJob.status == "processing")
        )
        stuck_jobs = result.scalars().all()

        if not stuck_jobs:
            return

        active_job_ids = _active_processing_job_ids()
        if active_job_ids is None:
            print("[startup] Celery active task 상태를 확인할 수 없어 processing 작업 복구를 건너뜁니다.")
            return

        active_jobs = [job for job in stuck_jobs if str(job.id) in active_job_ids]
        stuck_jobs = [job for job in stuck_jobs if str(job.id) not in active_job_ids]

        if active_jobs:
            print(
                "[startup] Celery가 실행/예약/대기 중인 처리 작업은 복구 대상에서 제외: "
                f"{[str(job.id) for job in active_jobs]}"
            )

        if not stuck_jobs:
            return

        celery_states = {
            job.id: _celery_task_state(job.celery_task_id)
            for job in stuck_jobs
        }
        backend_active_jobs = [
            job
            for job in stuck_jobs
            if celery_states.get(job.id) in {"STARTED", "RETRY", "RECEIVED"}
        ]
        if backend_active_jobs:
            print(
                "[startup] Celery backend가 실행 중으로 보고한 작업은 복구 대상에서 제외: "
                f"{[str(job.id) for job in backend_active_jobs]}"
            )
            stuck_jobs = [job for job in stuck_jobs if job not in backend_active_jobs]

        revoked_jobs = [
            job for job in stuck_jobs
            if celery_states.get(job.id) == "REVOKED"
        ]
        if revoked_jobs:
            revoked_job_ids = [job.id for job in revoked_jobs]
            revoked_project_ids = {job.project_id for job in revoked_jobs}
            now = datetime.utcnow()
            print(f"[startup] 취소된 처리 작업 {len(revoked_jobs)}건 복구 중...")
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id.in_(revoked_job_ids))
                .values(
                    status="cancelled",
                    completed_at=now,
                    error_message=None,
                )
            )
            await db.execute(
                update(Project)
                .where(
                    Project.id.in_(revoked_project_ids),
                    Project.status == "processing",
                )
                .values(status="cancelled")
            )
            for job in revoked_jobs:
                _write_cancelled_status_file(job)
            await db.commit()

        stuck_jobs = [job for job in stuck_jobs if job not in revoked_jobs]
        if not stuck_jobs:
            return

        completed_jobs = [
            job for job in stuck_jobs
            if (
                job.result_path
                or int(job.progress or 0) >= 100
                or _read_processing_status_file(job).get("status") == "completed"
            )
        ]
        if completed_jobs:
            completed_job_ids = [job.id for job in completed_jobs]
            completed_project_ids = {job.project_id for job in completed_jobs}
            now = datetime.utcnow()
            print(f"[startup] 완료 상태로 보이는 처리 작업 {len(completed_jobs)}건 복구 중...")
            await db.execute(
                update(ProcessingJob)
                .where(ProcessingJob.id.in_(completed_job_ids))
                .values(
                    status="completed",
                    progress=100,
                    completed_at=now,
                    error_message=None,
                )
            )
            unapplied_crs_job_ids = [
                job.id
                for job in completed_jobs
                if job.crs_correction_status == "pending" and job.result_path
            ]
            if unapplied_crs_job_ids:
                await db.execute(
                    update(ProcessingJob)
                    .where(ProcessingJob.id.in_(unapplied_crs_job_ids))
                    .values(
                        crs_correction_status="failed",
                        crs_correction_error=UNAPPLIED_CRS_CORRECTION_MESSAGE,
                    )
                )
            await db.execute(
                update(Project)
                .where(
                    Project.id.in_(completed_project_ids),
                    Project.status == "processing",
                )
                .values(status="completed", progress=100)
            )
            await db.commit()

        stuck_jobs = [job for job in stuck_jobs if job not in completed_jobs]
        if not stuck_jobs:
            return

        now = datetime.utcnow()
        grace_jobs = [
            job
            for job in stuck_jobs
            if startup_recovery_in_grace_period(
                created_at=job.created_at,
                started_at=job.started_at,
                now=now,
            )
        ]
        if grace_jobs:
            print(
                "[startup] 최근 시작된 처리 작업은 15분 복구 유예시간 동안 유지: "
                f"{[str(job.id) for job in grace_jobs]}"
            )
            stuck_jobs = [job for job in stuck_jobs if job not in grace_jobs]

        if not stuck_jobs:
            return

        stuck_job_ids = [job.id for job in stuck_jobs]
        stuck_project_ids = {job.project_id for job in stuck_jobs}
        print(f"[startup] 고착된 처리 작업 {len(stuck_jobs)}건 복구 중...")

        # processing_jobs → error로 전환
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.id.in_(stuck_job_ids))
            .values(
                status="error",
                error_message="서버 재시작(전원 차단)으로 인해 처리가 중단되었습니다. 다시 처리를 시작해주세요.",
            )
        )

        # 연결된 projects → error로 전환
        await db.execute(
            update(Project)
            .where(
                Project.id.in_(stuck_project_ids),
                Project.status == "processing",
            )
            .values(status="error")
        )

        await db.commit()
        print(f"[startup] {len(stuck_jobs)}건 복구 완료 (project_ids: {[str(p) for p in stuck_project_ids]})")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    # Startup
    print(f"Starting {settings.APP_NAME}...")
    await _recover_stuck_jobs()
    yield
    # Shutdown
    print(f"Shutting down {settings.APP_NAME}...")


app = FastAPI(
    title=settings.APP_NAME,
    description="항공/드론 정사영상 생성 및 프로젝트 관리 플랫폼",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Accept-Ranges", "X-File-Checksum"],
)

# Include API routers
app.include_router(api_v1_router, prefix=settings.API_V1_PREFIX)


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "app": settings.APP_NAME}
