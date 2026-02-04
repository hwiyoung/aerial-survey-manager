"""Project API endpoints."""
import re
import logging
from pathlib import Path
from typing import Optional
from uuid import UUID

logger = logging.getLogger(__name__)

from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, extract
from geoalchemy2.functions import ST_AsText

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image, ExteriorOrientation, ProcessingJob
from app.schemas.project import (
    ProjectCreate,
    ProjectUpdate,
    ProjectResponse,
    ProjectListResponse,
    EOConfig,
    EOUploadResponse,
    MonthlyStats,
    MonthlyStatsResponse,
    RegionalStats,
    RegionalStatsResponse,
)
from app.auth.jwt import get_current_user, PermissionChecker
from app.services.eo_parser import EOParserService
from app.utils.geo import get_region_for_point
from pyproj import Transformer
import json
from sqlalchemy import func

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
    
    # Filter by ownership or organization
    if current_user.role != "admin":
        query = query.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
    
    # Apply filters
    if status_filter:
        query = query.where(Project.status == status_filter)
    if region:
        query = query.where(Project.region == region)
    if search:
        query = query.where(Project.title.ilike(f"%{search}%"))
    
    # Count total (need separate count query)
    count_subquery = select(Project.id)
    if current_user.role != "admin":
        count_subquery = count_subquery.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
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

        # Get latest processing job for result_gsd and process_mode
        job_result = await db.execute(
            select(ProcessingJob)
            .where(ProcessingJob.project_id == project.id)
            .order_by(ProcessingJob.id.desc())
            .limit(1)
        )
        latest_job = job_result.scalar_one_or_none()
        result_gsd = latest_job.result_gsd if latest_job else None
        process_mode = latest_job.process_mode if latest_job else None

        # Convert ORM model to dict and serialize bounds BEFORE Pydantic validation
        project_dict = {
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
            "ortho_size": project.ortho_size,
            "area": project.area,
            "ortho_path": project.ortho_path,
            "bounds": serialize_geometry(bounds_wkt),  # Now using WKT string
            "upload_completed_count": upload_completed_count,
            "upload_in_progress": upload_uploading_count > 0,
            "result_gsd": result_gsd,
            "process_mode": process_mode,
        }
        response = ProjectResponse.model_validate(project_dict)
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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a new project."""
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
    
    response_dict = {
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
        "image_count": 0,
        "source_size": project.source_size,
        "ortho_size": project.ortho_size,
        "area": project.area,
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(project.bounds),
    }
    return ProjectResponse.model_validate(response_dict)


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

    # Get image count
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()

    # Get latest processing job for result_gsd and process_mode
    job_result = await db.execute(
        select(ProcessingJob)
        .where(ProcessingJob.project_id == project.id)
        .order_by(ProcessingJob.id.desc())
        .limit(1)
    )
    latest_job = job_result.scalar_one_or_none()
    result_gsd = latest_job.result_gsd if latest_job else None
    process_mode = latest_job.process_mode if latest_job else None

    response_dict = {
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
        "ortho_size": project.ortho_size,
        "area": project.area,
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(bounds_wkt),
        "result_gsd": result_gsd,
        "process_mode": process_mode,
    }
    return ProjectResponse.model_validate(response_dict)



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
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Update fields
    update_data = data.model_dump(exclude_unset=True)
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
    
    # Get image count
    count_result = await db.execute(
        select(func.count()).where(Image.project_id == project.id)
    )
    image_count = count_result.scalar()
    
    response_dict = {
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
        "ortho_size": project.ortho_size,
        "area": project.area,
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(bounds_wkt),
    }
    return ProjectResponse.model_validate(response_dict)



@router.delete("/{project_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_project(
    project_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete project and all related data."""
    # Check permission (only owner or admin can delete)
    permission_checker = PermissionChecker("admin")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only project owner or admin can delete projects",
        )
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
    # Get all image original_paths before deletion (for MinIO cleanup)
    image_result = await db.execute(
        select(Image.original_path).where(
            Image.project_id == project_id,
            Image.original_path.isnot(None)
        )
    )
    original_paths = [row[0] for row in image_result.fetchall()]

    await db.delete(project)

    # Clean up local processing data
    import shutil
    from app.config import get_settings
    settings = get_settings()
    local_path = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project_id)
    if local_path.exists():
        try:
            shutil.rmtree(local_path)
        except Exception as e:
            print(f"Failed to delete local project data {local_path}: {e}")

    # Clean up MinIO storage
    try:
        from app.services.storage import StorageService
        storage = StorageService()

        # Delete original uploaded images (stored in uploads/ by TUS)
        # TUS stores files as folders with chunks, so use delete_recursive
        for path in original_paths:
            try:
                # Delete the upload folder/file (TUS may create folder structure)
                storage.delete_recursive(f"{path}/")
                # Also try direct object deletion for single-file uploads
                try:
                    storage.delete_object(path)
                except Exception:
                    pass
                # Delete .info metadata folder/file created by TUS
                storage.delete_recursive(f"{path}.info/")
                try:
                    storage.delete_object(f"{path}.info")
                except Exception:
                    pass
            except Exception as e:
                print(f"Failed to delete uploaded file {path}: {e}")

        # Delete project folder (thumbnails, ortho results, etc.)
        storage.delete_recursive(f"projects/{project_id}/")
    except Exception as e:
        print(f"Failed to delete MinIO project data for {project_id}: {e}")
    
    # Note: Related images, jobs, etc. will be deleted via CASCADE


@router.post("/{project_id}/eo", response_model=EOUploadResponse)
async def upload_eo_data(
    project_id: UUID,
    file: UploadFile = File(...),
    config: str = Query("{}"),  # JSON string of EOConfig
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upload and parse EO data file for a project."""
    # Check permission
    permission_checker = PermissionChecker("edit")
    if not await permission_checker.check(str(project_id), current_user, db):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied",
        )
    
    # Parse config
    import json
    try:
        eo_config_data = json.loads(config)
        # Handle camelCase from frontend if Pydantic alias didn't catch it
        if "hasHeader" in eo_config_data and "has_header" not in eo_config_data:
            eo_config_data["has_header"] = eo_config_data["hasHeader"]
        
        # Ensure 'image_name' exists in columns if 'id' was sent
        if "columns" in eo_config_data:
            cols = eo_config_data["columns"]
            if "id" in cols and "image_name" not in cols:
                cols["image_name"] = cols["id"]
        
        eo_config = EOConfig(**eo_config_data)
    except Exception as e:
        logger.warning(f"EO Config parse warning: {e}. Using defaults.")
        eo_config = EOConfig()
        
    # Read file content
    content = (await file.read()).decode("utf-8")
    
    # Parse EO data
    delimiter = eo_config.delimiter
    if delimiter == "space":
        delimiter = " "
    elif delimiter == "tab":
        delimiter = "\t"
        
    # Fetch project
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    print(f"EO Upload: Starting parse with delimiter='{delimiter}', has_header={eo_config.has_header}")  # DEBUG
    print(f"EO Upload: Content first 200 chars: {content[:200]}")  # DEBUG
    try:
        parsed_rows = EOParserService.parse_eo_file(
            content=content,
            delimiter=delimiter,
            has_header=eo_config.has_header,
            columns=eo_config.columns
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse EO file: {str(e)}",
        )
    
    if not parsed_rows:
        return EOUploadResponse(parsed_count=0, matched_count=0, errors=["No valid data found in file"])
    
    # Get all images for this project to match by filename
    result = await db.execute(select(Image).where(Image.project_id == project_id))
    images = result.scalars().all()
    
    print(f"EO Upload: Found {len(images)} images for project {project_id}")  # DEBUG
    
    # improved matching logic
    import os
    image_map = {img.filename: img for img in images}
    # map stem (lowercase) to image for loose matching
    # e.g. "img_001" -> Image(filename="IMG_001.JPG")
    image_stem_map = {}
    for img in images:
        stem = os.path.splitext(img.filename)[0].lower()
        if stem not in image_stem_map:
            image_stem_map[stem] = img
    
    # Prepare EO records
    eo_records = []
    matched_count = 0
    errors = []
    
    # Clear existing EO for these images if any (to avoid unique constraint errors)
    # This is a simple overwrite policy
    parsed_filenames = [row.image_name for row in parsed_rows]
    valid_image_ids = [image_map[name].id for name in parsed_filenames if name in image_map]
    
    if valid_image_ids:
        await db.execute(
            delete(ExteriorOrientation).where(ExteriorOrientation.image_id.in_(valid_image_ids))
        )
    
    # Prepare Transformer if CRS is not WGS84
    transformer = None
    target_crs = "EPSG:4326"
    source_crs = eo_config.crs.upper()
    
    # Extract strict EPSG code using regex if present
    # Matches "EPSG:1234" or "EPSG: 1234"
    epsg_match = re.search(r'EPSG[:\s]+(\d+)', source_crs)
    if epsg_match:
        source_code = f"EPSG:{epsg_match.group(1)}"
        if source_code != target_crs:
             source_crs = source_code # Use clean code for pyproj
    
    # Handle common aliases or variations
    if "WGS84" in source_crs or source_crs == "EPSG:4326":
        transformer = None
        source_crs = "EPSG:4326"
    else:
        try:
            # always_xy=True: input is (x, y) [long/east, lat/north], output is (long, lat)
            from pyproj import Transformer
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        except Exception as e:
            # If CRS is invalid, we proceed with raw values
            logger.warning(f"Failed to create transformer for {source_crs}: {e}")
            transformer = None

    # Prepare EO records + reference file rows
    eo_objects = {}
    matched_count = 0
    errors = []
    reference_rows = []
    reference_keys = set()
    reference_crs = source_crs

    try:
        for row in parsed_rows:
            row_name = os.path.basename(row.image_name)
            # Transform if needed
            original_x = row.x
            original_y = row.y
            x_val = original_x
            y_val = original_y
            crs_val = source_crs
            if transformer:
                try:
                    lon, lat = transformer.transform(row.x, row.y)
                    x_val = lon
                    y_val = lat
                    crs_val = target_crs
                except Exception as e:
                    errors.append(f"Transform error for {row_name}: {e}")
                    continue

            # Matching logic
            image = image_map.get(row_name)
            if not image:
                 for fname, img_obj in image_map.items():
                     if fname.lower() == row_name.lower():
                         image = img_obj
                         break
            if not image:
                row_stem = os.path.splitext(row_name)[0].lower()
                image = image_stem_map.get(row_stem)

            if not image:
                errors.append(f"Image not found for filename: {row_name}")
                continue
            
            # Skip if we already processed this image in this file
            if image.id in eo_objects:
                continue
                
            eo = ExteriorOrientation(
                image_id=image.id,
                x=x_val,
                y=y_val,
                z=row.z,
                omega=row.omega,
                phi=row.phi,
                kappa=row.kappa,
                crs=crs_val
            )
            eo_objects[image.id] = eo

            # Collect reference rows only for matched images (dedup by name)
            row_key = row_name.lower()
            if row_key not in reference_keys:
                reference_rows.append((row_name, original_x, original_y, row.z, row.omega, row.phi, row.kappa))
                reference_keys.add(row_key)
            
            # Update image location (Point geometry)
            # Use string representation for GeoAlchemy2 to handle easily
            image.location = f"SRID=4326;POINT({x_val} {y_val})"
            matched_count += 1
            
        if matched_count > 0:
            # Delete any existing EO for THESE images only
            # The previous logic was slightly flawed in bulk delete if IDs weren't matched yet
            await db.execute(
                delete(ExteriorOrientation).where(ExteriorOrientation.image_id.in_(list(eo_objects.keys())))
            )
            
            # Add all new EO records
            for eo in eo_objects.values():
                db.add(eo)
            
            # Calculate project bounds from matched coordinates (WGS84)
            lons = [eo.x for eo in eo_objects.values()]
            lats = [eo.y for eo in eo_objects.values()]
            
            if lons and lats:
                min_lon, max_lon = min(lons), max(lons)
                min_lat, max_lat = min(lats), max(lats)
                
                # Check for "clumping" or invalid bounds (single point)
                # If it's a single point, we make a tiny box
                if min_lon == max_lon: min_lon -= 0.0001; max_lon += 0.0001
                if min_lat == max_lat: min_lat -= 0.0001; max_lat += 0.0001
                
                project.bounds = f"SRID=4326;POLYGON(({min_lon} {min_lat}, {max_lon} {min_lat}, {max_lon} {max_lat}, {min_lon} {max_lat}, {min_lon} {min_lat}))"
                
                # Auto-assign region based on EO data
                center_lon = (min_lon + max_lon) / 2
                center_lat = (min_lat + max_lat) / 2
                region = get_region_for_point(center_lon, center_lat)
                if region:
                    project.region = region

        if matched_count == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"EO 파일의 이미지명이 업로드된 이미지와 일치하지 않습니다. (matched 0/{len(parsed_rows)})"
            )

        # Save normalized EO reference file to local processing path for Metashape
        if reference_rows:
            try:
                from app.config import get_settings
                settings = get_settings()
                reference_dir = Path(settings.LOCAL_DATA_PATH) / "processing" / str(project_id) / "images"
                reference_dir.mkdir(parents=True, exist_ok=True)
                reference_path = reference_dir / "metadata.txt"
                with open(reference_path, "w", encoding="utf-8") as f:
                    if reference_crs:
                        f.write(f"# CRS {reference_crs}\n")
                    for name, x_val, y_val, z_val, omega, phi, kappa in reference_rows:
                        f.write(f"{name} {x_val} {y_val} {z_val} {omega} {phi} {kappa}\n")
                print(f"EO Upload: Saved reference file at {reference_path}")
            except Exception as e:
                logger.warning(f"EO Upload: Failed to save reference file: {e}")

        await db.commit()
    except Exception as e:
        import traceback
        logger.error(f"EO Upload Database Error: {str(e)}")
        logger.error(traceback.format_exc())
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Database error during EO save: {str(e)}"
        )
    
    return EOUploadResponse(
        parsed_count=len(parsed_rows),
        matched_count=matched_count,
        errors=errors[:10]  # Return first 10 errors
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
    if current_user.role != "admin":
        base_query = base_query.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
    
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
    if current_user.role != "admin":
        base_query = base_query.where(
            (Project.owner_id == current_user.id) |
            (Project.organization_id == current_user.organization_id)
        )
    
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
