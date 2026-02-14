"""Project API endpoints."""
import os
import re
import logging
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, extract
from geoalchemy2.functions import ST_AsText

from app.database import get_db
from app.models.user import User, ProjectPermission
from app.models.project import Project, Image, ExteriorOrientation, ProcessingJob
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    ProjectBatchAction,
    ProjectBatchResponse,
    ProjectBatchFailure,
    EOConfig,
    EOUploadResponse,
    MonthlyStats,
    MonthlyStatsResponse,
    RegionalStats,
    RegionalStatsResponse,
    StorageStatsResponse,
)
from app.auth.jwt import (
    get_current_user,
    get_current_active_manager,
    PermissionChecker,
    is_admin_role,
)
from app.config import get_settings
from app.services.eo_parser import EOParserService
from app.services.quota import ensure_organization_quota
from app.utils.geo import get_region_for_point, get_region_for_point_db
from app.utils.audit import log_audit_event
from pyproj import Transformer
import json

def serialize_geometry(geom):
    """Convert PostGIS geometry to GeoJSON-like list of coordinates.
    
    Uses WKT parsing to avoid shapely/numpy compatibility issues.
    """
    if geom is None:
        return None
    try:
        # Get WKT string from the geometry
        # For WKBElement, we need to convert it during query
        # This function expects WKT string as input now
        if hasattr(geom, 'desc'):
            # This is a WKBElement, we can't parse it here directly
            # Return None - the caller should use ST_AsText in the query
            return None
        
        wkt_str = str(geom)
        
        # Parse POLYGON WKT: POLYGON((lon1 lat1, lon2 lat2, ...))
        polygon_match = re.search(r'POLYGON\s*\(\(([^)]+)\)\)', wkt_str, re.IGNORECASE)
        if polygon_match:
            coords_str = polygon_match.group(1)
            coords = []
            for point in coords_str.split(','):
                parts = point.strip().split()
                if len(parts) >= 2:
                    lon = float(parts[0])
                    lat = float(parts[1])
                    coords.append([lat, lon])  # [lat, lng] for Leaflet
            return coords if coords else None
            
        # Parse POINT WKT: POINT(lon lat)
        point_match = re.search(r'POINT\s*\(([^)]+)\)', wkt_str, re.IGNORECASE)
        if point_match:
            parts = point_match.group(1).strip().split()
            if len(parts) >= 2:
                lon = float(parts[0])
                lat = float(parts[1])
                return [lat, lon]  # [lat, lng] for Leaflet
                
    except Exception as e:
        print(f"Geometry serialization error: {e}")
    return None

router = APIRouter(prefix="/projects", tags=["Projects"])


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
    """Apply organization-first access scope for non-admin users."""
    if is_admin_role(current_user.role):
        return query

    if current_user.organization_id is not None:
        return query.where(Project.organization_id == current_user.organization_id)

    return query.where(Project.owner_id == current_user.id)


def _resolve_project_permission(
    project: Project,
    current_user: User,
    explicit_permission: Optional[str] = None,
) -> Optional[str]:
    """Resolve effective permission for current user on a project."""
    if is_admin_role(current_user.role):
        return "admin"

    if project.owner_id == current_user.id:
        return "admin"

    if explicit_permission in {"view", "edit", "admin"}:
        return explicit_permission

    if project.organization_id == current_user.organization_id:
        return "view"

    return None


def _build_project_access_fields(
    project: Project,
    current_user: User,
    explicit_permission: Optional[str] = None,
) -> dict:
    permission = _resolve_project_permission(project, current_user, explicit_permission)
    return {
        "current_user_permission": permission,
        "can_edit": permission in {"edit", "admin"},
        "can_delete": permission == "admin",
    }


async def _get_explicit_permission_map(
    db: AsyncSession,
    current_user: User,
    project_ids: list[UUID],
) -> dict[UUID, str]:
    if is_admin_role(current_user.role) or not project_ids:
        return {}

    unique_project_ids = list(dict.fromkeys(project_ids))
    result = await db.execute(
        select(ProjectPermission.project_id, ProjectPermission.permission).where(
            ProjectPermission.user_id == current_user.id,
            ProjectPermission.project_id.in_(unique_project_ids),
        )
    )
    return {project_id: permission for project_id, permission in result.all()}


async def _collect_project_image_paths(
    project_id: UUID,
    db: AsyncSession,
) -> list[str]:
    """Collect original image paths for cleanup before deleting a project."""
    image_result = await db.execute(
        select(Image.original_path).where(
            Image.project_id == project_id,
            Image.original_path.isnot(None),
        )
    )
    return [row[0] for row in image_result.fetchall()]


def _cleanup_project_storage(project_id: UUID, original_paths: list[str]) -> None:
    """Delete project files from object storage."""
    try:
        from app.services.storage import get_storage
        storage = get_storage()

        for path in original_paths:
            try:
                storage.delete_recursive(f"{path}/")
                try:
                    storage.delete_object(path)
                except Exception:
                    pass
                storage.delete_recursive(f"{path}.info/")
                try:
                    storage.delete_object(f"{path}.info")
                except Exception:
                    pass
            except Exception as e:
                print(f"Failed to delete uploaded file {path}: {e}")

        storage.delete_recursive(f"projects/{project_id}/")
    except Exception as e:
        print(f"Failed to delete MinIO project data for {project_id}: {e}")


def _build_project_response(project, bounds_wkt=None, image_count=0, **extra) -> ProjectResponse:
    """Build a ProjectResponse dict from ORM model and optional extras.

    Common fields are extracted from the project; additional fields
    (result_gsd, process_mode, upload_completed_count, etc.) are passed via **extra.
    """
    d = {
        "id": project.id,
        "title": project.title,
        "region": project.region,
        "company": project.company,
        "status": project.status,
        "progress": project.progress,
        "owner_id": project.owner_id,
        "organization_id": project.organization_id,
        "group_id": project.group_id,
        "created_at": project.created_at,
        "updated_at": project.updated_at,
        "image_count": image_count,
        "source_size": project.source_size,
        "source_deleted": project.source_deleted,
        "ortho_size": project.ortho_size,
        "area": project.area,
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(bounds_wkt if bounds_wkt is not None else project.bounds),
    }
    d.update(extra)
    return ProjectResponse.model_validate(d)


@router.get("", response_model=ProjectListResponse)
async def list_projects(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    region: Optional[str] = None,
    search: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List projects accessible by the current user."""
    # Build query based on user's access - include ST_AsText for bounds
    query = select(
        Project,
        ST_AsText(Project.bounds).label('bounds_wkt')
    )
    
    query = _apply_project_access_scope(query, current_user)
    
    # Apply filters
    if status_filter:
        query = query.where(Project.status == status_filter)
    if region:
        query = query.where(Project.region == region)
    if search:
        query = query.where(Project.title.ilike(f"%{search}%"))
    
    # Count total (need separate count query)
    count_subquery = select(Project.id)
    count_subquery = _apply_project_access_scope(count_subquery, current_user)
    if status_filter:
        count_subquery = count_subquery.where(Project.status == status_filter)
    if region:
        count_subquery = count_subquery.where(Project.region == region)
    if search:
        count_subquery = count_subquery.where(Project.title.ilike(f"%{search}%"))
    
    count_query = select(func.count()).select_from(count_subquery.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Paginate
    query = query.order_by(Project.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    rows = result.all()

    explicit_permission_map = await _get_explicit_permission_map(
        db,
        current_user,
        [row[0].id for row in rows],
    )
    
    # Add image count to each project
    project_responses = []
    for row in rows:
        project = row[0]
        bounds_wkt = row[1]
        
        # 이미지 수 및 업로드 상태 집계
        count_result = await db.execute(
            select(func.count()).where(Image.project_id == project.id)
        )
        image_count = count_result.scalar()

        # 업로드 상태별 집계
        upload_status_result = await db.execute(
            select(
                Image.upload_status,
                func.count(Image.id).label("count")
            )
            .where(Image.project_id == project.id)
            .group_by(Image.upload_status)
        )
        status_counts = {row.upload_status: row.count for row in upload_status_result}
        upload_completed_count = status_counts.get("completed", 0)
        upload_uploading_count = status_counts.get("uploading", 0)

        # Get latest COMPLETED processing job for result_gsd and process_mode
        # (Filter by status='completed' to avoid getting cancelled/error jobs with no GSD)
        job_result = await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.project_id == project.id)
            .where(ProcessingJob.status == "completed")
            .order_by(ProcessingJob.started_at.desc())
            .limit(1)
        )
        latest_job = job_result.scalar_one_or_none()

        # Fallback to any job for process_mode if no completed job
        if not latest_job:
            fallback_result = await db.execute(
                select(ProcessingJob)
                .where(ProcessingJob.project_id == project.id)
                .order_by(ProcessingJob.started_at.desc())
                .limit(1)
            )
            latest_job = fallback_result.scalar_one_or_none()

        result_gsd = latest_job.result_gsd if latest_job else None
        process_mode = latest_job.process_mode if latest_job else None

        response = _build_project_response(
            project, bounds_wkt=bounds_wkt, image_count=image_count,
            upload_completed_count=upload_completed_count,
            upload_in_progress=upload_uploading_count > 0,
            result_gsd=result_gsd, process_mode=process_mode,
            **_build_project_access_fields(
                project,
                current_user,
                explicit_permission_map.get(project.id),
            ),
        )
        project_responses.append(response)
    
    return ProjectListResponse(
        items=project_responses,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    data: ProjectCreate,
    current_user: User = Depends(get_current_active_manager),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
    if current_user.organization_id is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User has no organization assigned.",
        )

    await ensure_organization_quota(
        db,
        current_user.organization_id,
        additional_projects=1,
    )

    project = Project(
        title=data.title,
        region=data.region or "미지정",
        company=data.company,
        owner_id=current_user.id,
        organization_id=current_user.organization_id,
    )
    db.add(project)
    await db.flush()
    await db.refresh(project)

    log_audit_event(
        "project_created",
        actor=current_user,
        details={
            "project_id": str(project.id),
            "project_title": project.title,
            "owner_id": str(project.owner_id),
            "organization_id": str(project.organization_id),
            "region": project.region,
            "company": project.company,
        },
    )
    
    return _build_project_response(
        project,
        **_build_project_access_fields(project, current_user),
    )


@router.get("/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get project details."""
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
    
    # Fetch with ST_AsText for bounds
    result = await db.execute(
        select(Project, ST_AsText(Project.bounds).label('bounds_wkt'))
        .where(Project.id == project_id)
    )
    row = result.first()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    project = row[0]
    bounds_wkt = row[1]

    explicit_permission_map = await _get_explicit_permission_map(
        db,
        current_user,
        [project.id],
    )

    # Get image count
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()

    # Get latest COMPLETED processing job for result_gsd and process_mode
    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project.id)
        .where(ProcessingJob.status == "completed")
        .order_by(ProcessingJob.started_at.desc())
        .limit(1)
    )
    latest_job = job_result.scalar_one_or_none()

    # Fallback to any job for process_mode if no completed job
    if not latest_job:
        fallback_result = await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.project_id == project.id)
            .order_by(ProcessingJob.started_at.desc())
            .limit(1)
        )
        latest_job = fallback_result.scalar_one_or_none()

    result_gsd = latest_job.result_gsd if latest_job else None
    process_mode = latest_job.process_mode if latest_job else None

    return _build_project_response(
        project, bounds_wkt=bounds_wkt, image_count=image_count,
        result_gsd=result_gsd, process_mode=process_mode,
        **_build_project_access_fields(
            project,
            current_user,
            explicit_permission_map.get(project.id),
        ),
    )



@router.patch("/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    data: ProjectUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update project."""
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
    project = scoped_project
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
    previous_values = {
        field: getattr(project, field)
        for field in update_data
    }
    for field, value in update_data.items():
        setattr(project, field, value)
    
    await db.flush()
    
    # Re-fetch with ST_AsText for bounds
    result = await db.execute(
        select(Project, ST_AsText(Project.bounds).label('bounds_wkt'))
        .where(Project.id == project_id)
    )
    row = result.first()
    project = row[0]
    bounds_wkt = row[1]

    explicit_permission_map = await _get_explicit_permission_map(
        db,
        current_user,
        [project.id],
    )
    
    # Get image count and upload status
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()

    upload_status_result = await db.execute(
        select(
            Image.upload_status,
            func.count(Image.id).label("count")
        )
        .where(Image.project_id == project.id)
        .group_by(Image.upload_status)
    )
    status_counts = {row.upload_status: row.count for row in upload_status_result}
    upload_completed_count = status_counts.get("completed", 0)
    upload_uploading_count = status_counts.get("uploading", 0)

    # Get latest COMPLETED processing job for result_gsd and process_mode
    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project.id)
        .where(ProcessingJob.status == "completed")
        .order_by(ProcessingJob.started_at.desc())
        .limit(1)
    )
    latest_job = job_result.scalar_one_or_none()

    if not latest_job:
        fallback_result = await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.project_id == project.id)
            .order_by(ProcessingJob.started_at.desc())
            .limit(1)
        )
        latest_job = fallback_result.scalar_one_or_none()

    result_gsd = latest_job.result_gsd if latest_job else None
    process_mode = latest_job.process_mode if latest_job else None

    if update_data:
        change_log = {
            "project_id": str(project.id),
            "project_title": project.title,
            "updated_fields": sorted(update_data.keys()),
            "changes": [
                {
                    "field": field,
                    "previous": previous_values.get(field),
                    "new": update_data[field],
                }
                for field in sorted(update_data.keys())
            ],
        }
        log_audit_event(
            "project_updated",
            actor=current_user,
            details=change_log,
        )

    return _build_project_response(
        project, bounds_wkt=bounds_wkt, image_count=image_count,
        upload_completed_count=upload_completed_count,
        upload_in_progress=upload_uploading_count > 0,
        result_gsd=result_gsd, process_mode=process_mode,
        **_build_project_access_fields(
            project,
            current_user,
            explicit_permission_map.get(project.id),
        ),
    )



@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT, deprecated=True)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deprecated. Use POST /projects/batch with action='delete'."""
    raise HTTPException(
        status_code=status.HTTP_405_METHOD_NOT_ALLOWED,
        detail={
            "type": "deprecated_endpoint",
            "message": "This endpoint is deprecated. Use POST /projects/batch with action='delete'.",
            "project_id": str(project_id),
        },
    )


@router.post("/batch", response_model=ProjectBatchResponse)
async def batch_projects(
    payload: ProjectBatchAction,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Batch operation for projects."""
    if payload.action == "update_status" and not payload.status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="status is required when action is update_status",
        )

    unique_ids = list(dict.fromkeys(payload.project_ids))
    permission_checker = PermissionChecker("admin" if payload.action == "delete" else "edit")

    succeeded = []
    failed = []

    for project_id in unique_ids:
        project_id_str = str(project_id)
        if not await permission_checker.check(project_id_str, current_user, db):
            failed.append(
                ProjectBatchFailure(
                    project_id=project_id,
                    reason="Permission denied",
                )
            )
            continue

        project = await _get_scoped_project(project_id, current_user, db)
        if not project:
            failed.append(
                ProjectBatchFailure(
                    project_id=project_id,
                    reason="Project not found",
                )
            )
            continue

        try:
            project_title = project.title
            if payload.action == "delete":
                original_paths = await _collect_project_image_paths(project_id, db)

                async with db.begin_nested():
                    await db.delete(project)
                await db.commit()

                from app.workers.tasks import delete_project_data
                try:
                    delete_project_data.delay(str(project_id))
                except Exception as e:
                    print(f"Failed to queue delete task for {project_id}: {e}")
                _cleanup_project_storage(project_id, original_paths)
                log_audit_event(
                    "project_batch_deleted",
                    actor=current_user,
                    details={
                        "project_id": project_id_str,
                        "project_title": project_title,
                    },
                )
                succeeded.append(project_id)

            elif payload.action == "update_status":
                previous_status = project.status
                project.status = payload.status
                await db.commit()
                log_audit_event(
                    "project_batch_status_updated",
                    actor=current_user,
                    details={
                        "project_id": project_id_str,
                        "project_title": project_title,
                        "previous_status": previous_status,
                        "new_status": payload.status,
                    },
                )
                succeeded.append(project_id)

        except HTTPException:
            raise
        except Exception as e:
            await db.rollback()
            failed.append(ProjectBatchFailure(project_id=project_id, reason=str(e)))

    log_audit_event(
        "project_batch_completed",
        actor=current_user,
        details={
            "action": payload.action,
            "requested": len(unique_ids),
            "succeeded": len(succeeded),
            "failed": len(failed),
        },
    )

    return ProjectBatchResponse(
        action=payload.action,
        requested=len(unique_ids),
        succeeded=succeeded,
        failed=failed,
    )


@router.delete("/{project_id}/source-images", status_code=status.HTTP_202_ACCEPTED)
async def delete_source_images(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    프로젝트의 원본 이미지를 삭제합니다 (MinIO + 썸네일).
    처리가 완료된 프로젝트에서만 사용 가능합니다.
    삭제 후 재처리가 불가능합니다.
    """
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Project not found")
    project = scoped_project

    if project.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="원본 이미지 삭제는 처리가 완료된 프로젝트에서만 가능합니다.",
        )

    if project.source_deleted:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="이미 원본 이미지가 삭제된 프로젝트입니다.",
        )

    # Set source_deleted immediately so API responses reflect the change
    # (Celery task will revert on failure)
    project.source_deleted = True
    await db.commit()

    # Queue Celery task for actual file deletion
    from app.workers.tasks import delete_source_images as delete_source_task
    try:
        delete_source_task.delay(str(project_id))
    except Exception as e:
        # Revert DB flag if task queue fails
        project.source_deleted = False
        await db.commit()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"삭제 작업 큐 등록 실패: {str(e)}",
        )

    return {"message": "원본 이미지 삭제가 시작되었습니다.", "project_id": str(project_id)}


def _parse_eo_config(config_json: str) -> EOConfig:
    """Parse and normalize EO config from JSON string."""
    try:
        data = json.loads(config_json)
        if "hasHeader" in data and "has_header" not in data:
            data["has_header"] = data["hasHeader"]
        if "columns" in data:
            cols = data["columns"]
            if "id" in cols and "image_name" not in cols:
                cols["image_name"] = cols["id"]
        return EOConfig(**data)
    except Exception as e:
        logger.warning(f"EO Config parse warning: {e}. Using defaults.")
        return EOConfig()


def _setup_crs_transformer(source_crs_raw: str):
    """Setup CRS transformer if source CRS differs from WGS84.

    Returns (transformer_or_None, clean_source_crs).
    """
    target_crs = "EPSG:4326"
    source_crs = source_crs_raw.upper()

    epsg_match = re.search(r'EPSG[:\s]+(\d+)', source_crs)
    if epsg_match:
        source_code = f"EPSG:{epsg_match.group(1)}"
        if source_code != target_crs:
            source_crs = source_code

    if "WGS84" in source_crs or source_crs == "EPSG:4326":
        return None, "EPSG:4326"

    try:
        transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        return transformer, source_crs
    except Exception as e:
        logger.warning(f"Failed to create transformer for {source_crs}: {e}")
        return None, source_crs


def _find_matching_image(row_name: str, image_map: dict, image_stem_map: dict):
    """Find matching image using exact, case-insensitive, and stem matching."""
    image = image_map.get(row_name)
    if not image:
        for fname, img_obj in image_map.items():
            if fname.lower() == row_name.lower():
                image = img_obj
                break
    if not image:
        row_stem = os.path.splitext(row_name)[0].lower()
        image = image_stem_map.get(row_stem)
    return image


def _match_eo_rows(parsed_rows, image_map, image_stem_map, transformer, source_crs):
    """Match parsed EO rows to images and create EO records.

    Returns (eo_objects, reference_rows, reference_crs, matched_count, errors).
    """
    target_crs = "EPSG:4326"
    eo_objects = {}
    reference_rows = []
    reference_keys = set()
    matched_count = 0
    errors = []

    for row in parsed_rows:
        row_name = os.path.basename(row.image_name)
        original_x, original_y = row.x, row.y
        x_val, y_val = original_x, original_y
        crs_val = source_crs

        if transformer:
            try:
                lon, lat = transformer.transform(row.x, row.y)
                x_val, y_val = lon, lat
                crs_val = target_crs
            except Exception as e:
                errors.append(f"Transform error for {row_name}: {e}")
                continue

        image = _find_matching_image(row_name, image_map, image_stem_map)
        if not image:
            errors.append(f"Image not found for filename: {row_name}")
            continue

        if image.id in eo_objects:
            continue

        eo = ExteriorOrientation(
            image_id=image.id,
            x=x_val, y=y_val, z=row.z,
            omega=row.omega, phi=row.phi, kappa=row.kappa,
            crs=crs_val,
        )
        eo_objects[image.id] = eo

        row_key = row_name.lower()
        if row_key not in reference_keys:
            reference_rows.append((row_name, original_x, original_y, row.z, row.omega, row.phi, row.kappa))
            reference_keys.add(row_key)

        image.location = f"SRID=4326;POINT({x_val} {y_val})"
        matched_count += 1

    return eo_objects, reference_rows, source_crs, matched_count, errors


@router.post("/{project_id}/eo", response_model=EOUploadResponse)
async def upload_eo_data(
    project_id: UUID,
    file: UploadFile = File(...),
    config: str = Query("{}"),  # JSON string of EOConfig
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload and parse EO data file for a project."""
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied")

    scoped_project = await _get_scoped_project(project_id, current_user, db)
    if not scoped_project:
        raise HTTPException(status_code=404, detail="Project not found")

    project = scoped_project

    eo_config = _parse_eo_config(config)

    content = (await file.read()).decode("utf-8")
    delimiter = eo_config.delimiter
    if delimiter == "space":
        delimiter = " "
    elif delimiter == "tab":
        delimiter = "\t"

    try:
        parsed_rows = EOParserService.parse_eo_file(
            content=content, delimiter=delimiter,
            has_header=eo_config.has_header, columns=eo_config.columns,
        )
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Failed to parse EO file: {str(e)}")

    if not parsed_rows:
        return EOUploadResponse(parsed_count=0, matched_count=0, errors=["No valid data found in file"])

    # Build image lookup maps
    result = await db.execute(select(Image).where(Image.project_id == project_id))
    images = result.scalars().all()

    image_map = {img.filename: img for img in images}
    image_stem_map = {}
    for img in images:
        stem = os.path.splitext(img.filename)[0].lower()
        if stem not in image_stem_map:
            image_stem_map[stem] = img

    # Setup CRS transformer
    transformer, source_crs = _setup_crs_transformer(eo_config.crs)

    # Match EO rows to images
    eo_objects, reference_rows, reference_crs, matched_count, errors = _match_eo_rows(
        parsed_rows, image_map, image_stem_map, transformer, source_crs,
    )

    try:
        if matched_count > 0:
            await db.execute(
                delete(ExteriorOrientation).where(ExteriorOrientation.image_id.in_(list(eo_objects.keys())))
            )
            for eo in eo_objects.values():
                db.add(eo)

            # Calculate project bounds from matched coordinates
            lons = [eo.x for eo in eo_objects.values()]
            lats = [eo.y for eo in eo_objects.values()]

            if lons and lats:
                min_lon, max_lon = min(lons), max(lons)
                min_lat, max_lat = min(lats), max(lats)
                if min_lon == max_lon: min_lon -= 0.0001; max_lon += 0.0001
                if min_lat == max_lat: min_lat -= 0.0001; max_lat += 0.0001

                project.bounds = f"SRID=4326;POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"

                center_lon = (min_lon + max_lon) / 2
                center_lat = (min_lat + max_lat) / 2
                region = await get_region_for_point_db(db, center_lon, center_lat)
                if region:
                    project.region = region

        if matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"EO 파일의 이미지명이 업로드된 이미지와 일치하지 않습니다. (matched 0/{len(parsed_rows)})",
            )

        # Save reference file via Celery task
        if reference_rows:
            try:
                from app.workers.tasks import save_eo_metadata
                save_eo_metadata.delay(str(project_id), reference_crs, reference_rows)
            except Exception as e:
                logger.warning(f"EO Upload: Failed to queue save task: {e}")

        await db.commit()
    except HTTPException:
        raise
    except Exception as e:
        import traceback
        logger.error(f"EO Upload Database Error: {str(e)}")
        logger.error(traceback.format_exc())
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during EO save: {str(e)}",
        )

    return EOUploadResponse(
        parsed_count=len(parsed_rows),
        matched_count=matched_count,
        errors=errors[:10],
    )


# --- Statistics Endpoints ---

@router.get("/stats/monthly", response_model=MonthlyStatsResponse)
async def get_monthly_stats(
    year: int = Query(None, description="Year to get stats for. Defaults to current year."),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get monthly project statistics for a given year."""
    from datetime import datetime as dt
    
    if year is None:
        year = dt.now().year
    
    # Build base query with user access filter
    base_query = select(Project)
    base_query = _apply_project_access_scope(base_query, current_user)
    
    # Filter by year
    base_query = base_query.where(
        extract('year', Project.created_at) == year
    )
    
    # Get all projects for the year to calculate stats
    result = await db.execute(base_query)
    projects = result.scalars().all()
    
    # Aggregate by month
    monthly_data = {}
    for month in range(1, 13):
        monthly_data[month] = {"count": 0, "completed": 0, "processing": 0}
    
    for project in projects:
        month = project.created_at.month
        monthly_data[month]["count"] += 1
        if project.status == "completed":
            monthly_data[month]["completed"] += 1
        elif project.status == "processing":
            monthly_data[month]["processing"] += 1
    
    # Build response
    stats_list = [
        MonthlyStats(
            month=month,
            year=year,
            count=data["count"],
            completed=data["completed"],
            processing=data["processing"]
        )
        for month, data in monthly_data.items()
    ]
    
    return MonthlyStatsResponse(year=year, data=stats_list)


@router.get("/stats/regional", response_model=RegionalStatsResponse)
async def get_regional_stats(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get regional project distribution statistics."""
    # Build base query with user access filter
    base_query = select(Project)
    base_query = _apply_project_access_scope(base_query, current_user)
    
    result = await db.execute(base_query)
    projects = result.scalars().all()
    
    # Aggregate by region
    region_counts = {}
    total = len(projects)
    
    for project in projects:
        region = project.region or "미지정"
        region_counts[region] = region_counts.get(region, 0) + 1
    
    # Build response with percentages
    stats_list = [
        RegionalStats(
            region=region,
            count=count,
            percentage=round((count / total * 100) if total > 0 else 0, 1)
        )
        for region, count in sorted(region_counts.items(), key=lambda x: x[1], reverse=True)
    ]
    
    return RegionalStatsResponse(total=total, data=stats_list)


_storage_cache: dict = {"data": None, "ts": 0}
_storage_cache_lock: "asyncio.Lock | None" = None
_storage_cache_lock_init = __import__("threading").Lock()
_last_refresh_ts: float = 0  # Global rate limit for refresh=true requests


def _get_storage_lock():
    """Lazy-init asyncio.Lock (thread-safe, must be called inside event loop)."""
    import asyncio
    global _storage_cache_lock
    if _storage_cache_lock is None:
        with _storage_cache_lock_init:
            if _storage_cache_lock is None:
                _storage_cache_lock = asyncio.Lock()
    return _storage_cache_lock


def _get_dir_size(path: str) -> int:
    """Get directory size using du -sb. Returns 0 if path doesn't exist."""
    import subprocess
    try:
        result = subprocess.run(
            ["du", "-sb", path],
            capture_output=True, text=True, timeout=300,
        )
        if result.returncode == 0:
            parts = result.stdout.split()
            if parts and parts[0].isdigit():
                return int(parts[0])
            logger.warning("du -sb %s: unexpected output: %s", path, result.stdout.strip())
        else:
            logger.warning("du -sb %s failed (rc=%d): %s", path, result.returncode, result.stderr.strip())
    except subprocess.TimeoutExpired:
        logger.warning("du -sb %s timed out (300s)", path)
    except Exception as e:
        logger.warning("du -sb %s error: %s", path, e)
    return 0


@router.get("/stats/storage", response_model=StorageStatsResponse)
async def get_storage_stats(
    refresh: bool = False,
    current_user: User = Depends(get_current_user),
):
    """Get per-directory storage sizes (MinIO, processing, tiles).

    Results are cached for 5 minutes since du scans can be slow on large directories.
    Pass refresh=true to bypass cache (e.g., after source image deletion).
    Refresh is rate-limited to once per 60 seconds to prevent du scan abuse.
    """
    import asyncio
    import time

    global _last_refresh_ts

    now = time.time()

    # Rate limit refresh requests (1 per 60s globally)
    if refresh and now - _last_refresh_ts < 60:
        refresh = False  # Fall back to cache behavior

    if not refresh and _storage_cache["data"] and now - _storage_cache["ts"] < 300:
        return _storage_cache["data"]

    # Prevent concurrent du scans from multiple requests
    async with _get_storage_lock():
        # Re-check after acquiring lock (another request may have refreshed)
        now = time.time()
        if refresh and now - _last_refresh_ts < 60:
            refresh = False
        if not refresh and _storage_cache["data"] and now - _storage_cache["ts"] < 300:
            return _storage_cache["data"]

        # Determine storage directory based on backend
        settings = get_settings()
        if settings.STORAGE_BACKEND == "local":
            storage_dir = settings.LOCAL_STORAGE_PATH
        else:
            # Scan only the aerial-survey bucket, not the entire MinIO data dir
            storage_dir = f"/data/minio/{settings.MINIO_BUCKET}"

        # Run du -sb in parallel threads (bind mounts from host)
        storage_size, processing_size, tiles_size = await asyncio.gather(
            asyncio.to_thread(_get_dir_size, storage_dir),
            asyncio.to_thread(_get_dir_size, "/data/processing"),
            asyncio.to_thread(_get_dir_size, "/data/tiles"),
        )

        resp = StorageStatsResponse(
            storage_size=storage_size,
            processing_size=processing_size,
            tiles_size=tiles_size,
            storage_backend=settings.STORAGE_BACKEND,
        )
        _storage_cache["data"] = resp
        _storage_cache["ts"] = now
        if refresh:
            _last_refresh_ts = now
        return resp
