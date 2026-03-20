"""FastAPI application entry point."""
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import update, select

from app.config import get_settings
from app.api.v1 import router as api_v1_router
from app.database import async_session
from app.models.project import ProcessingJob, Project

settings = get_settings()


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

        stuck_project_ids = {job.project_id for job in stuck_jobs}
        print(f"[startup] 고착된 처리 작업 {len(stuck_jobs)}건 복구 중...")

        # processing_jobs → error로 전환
        await db.execute(
            update(ProcessingJob)
            .where(ProcessingJob.status == "processing")
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
