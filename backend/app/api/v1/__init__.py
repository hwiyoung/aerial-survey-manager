"""API v1 router aggregation."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.projects import router as projects_router
from app.api.v1.upload import router as upload_router
from app.api.v1.download import router as download_router
from app.api.v1.processing import router as processing_router
from app.api.v1.users import router as users_router
from app.api.v1.camera_models import router as camera_models_router
from app.api.v1.presets import router as presets_router
from app.api.v1.groups import router as groups_router
from app.api.v1.permissions import router as permissions_router
from app.api.v1.organizations import router as organizations_router
from app.api.v1.regions import router as regions_router
from app.api.v1.storage_files import router as storage_files_router

router = APIRouter()

router.include_router(auth_router)
router.include_router(projects_router)
router.include_router(upload_router)
router.include_router(download_router)
router.include_router(processing_router)
router.include_router(users_router)
router.include_router(camera_models_router)
router.include_router(presets_router)
router.include_router(permissions_router)
router.include_router(groups_router)
router.include_router(organizations_router)
router.include_router(regions_router)
router.include_router(storage_files_router)
