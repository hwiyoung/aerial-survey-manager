"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.projects import router as projects_router
from app.api.v1.upload import router as upload_router
from app.api.v1.download import router as download_router
from app.api.v1.processing import router as processing_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(projects_router)
router.include_router(upload_router)
router.include_router(download_router)
router.include_router(processing_router)
