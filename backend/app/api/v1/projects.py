"""Project API endpoints."""
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status, File, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, delete, extract

from app.database import get_db
from app.models.user import User
from app.models.project import Project, Image, ExteriorOrientation
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
import re
from app.auth.jwt import get_current_user, PermissionChecker
from app.services.eo_parser import EOParserService
from pyproj import Transformer
from geoalchemy2.shape import to_shape
import json

def serialize_geometry(geom):
    """Convert PostGIS geometry to GeoJSON-like list of coordinates."""
    if geom is None:
        return None
    try:
        shape = to_shape(geom)
        if shape.geom_type == 'Polygon':
            # Return as list of [lat, lng] for Leaflet
            return [[p[1], p[0]] for p in shape.exterior.coords]
        elif shape.geom_type == 'Point':
            return [shape.y, shape.x]
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
    # Build query based on user's access
    query = select(Project)
    
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
    
    # Count total
    count_query = select(func.count()).select_from(query.subquery())
    total_result = await db.execute(count_query)
    total = total_result.scalar()
    
    # Paginate
    query = query.order_by(Project.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    
    result = await db.execute(query)
    projects = result.scalars().all()
    
    # Add image count to each project
    project_responses = []
    for project in projects:
        count_result = await db.execute(
            select(func.count()).where(Image.project_id == project.id)
        )
        image_count = count_result.scalar()
        
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
            "ortho_path": project.ortho_path,
            "bounds": serialize_geometry(project.bounds),  # Serialize BEFORE validation
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
        region=data.region,
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
    
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    
    if not project:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )
    
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
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(project.bounds),
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
    await db.refresh(project)
    
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
        "ortho_path": project.ortho_path,
        "bounds": serialize_geometry(project.bounds),
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
        eo_config = EOConfig(**eo_config_data)
    except Exception:
        eo_config = EOConfig()
        
    # Read file content
    content = (await file.read()).decode("utf-8")
    
    # Parse EO data
    delimiter = eo_config.delimiter
    if delimiter == "space":
        delimiter = " "
    elif delimiter == "tab":
        delimiter = "\t"
        
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
    else:
        try:
            # always_xy=True: input is (x, y) [long/east, lat/north], output is (long, lat)
            transformer = Transformer.from_crs(source_crs, target_crs, always_xy=True)
        except Exception as e:
            # If CRS is invalid, we proceed with raw values (or could raise error)
            print(f"Failed to create transformer for {source_crs}: {e}")
            pass

    for row in parsed_rows:
        # 1. Try exact match
        image = image_map.get(row.image_name)
        
        # 2. Try exact match with lowercase (if file system convention differs)
        if not image:
             # Find case-insensitive match in full filenames
             # This is O(N) per row, optimization possible but OK for 1000 images
             for fname, img_obj in image_map.items():
                 if fname.lower() == row.image_name.lower():
                     image = img_obj
                     break

        # 3. Try stem match (if EO name has no extension)
        if not image:
            row_stem = os.path.splitext(row.image_name)[0].lower()
            image = image_stem_map.get(row_stem)

        if not image:
            errors.append(f"Image not found for filename: {row.image_name}")
            continue
            
        x_val = row.x
        y_val = row.y
        crs_val = source_crs
        
        # Transform keys if needed
        if transformer:
            try:
                # Transform returns (lon, lat) because always_xy=True and target is 4326
                # row.x (Easting), row.y (Northing) -> lon, lat
                lon, lat = transformer.transform(row.x, row.y)
                x_val = lon
                y_val = lat
                crs_val = target_crs # Stored as WGS84
            except Exception as e:
                errors.append(f"Transform error for {row.image_name}: {e}")
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
        db.add(eo)
        
        # Update image location (Point geometry)
        # Use WGS84 coordinates (x_val=lon, y_val=lat)
        image.location = f"SRID=4326;POINT({x_val} {y_val})"
        
        matched_count += 1
        
    await db.commit()
    
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

