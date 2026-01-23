"""Regions API endpoints."""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
import json

from app.database import get_db

router = APIRouter(prefix="/regions", tags=["Regions"])

@router.get("/boundaries")
async def get_region_boundaries(db: AsyncSession = Depends(get_db)):
    """
    Get all regional boundaries as a GeoJSON FeatureCollection.
    Transforms coordinates to EPSG:4326 for web mapping.
    """
    query = text("""
        SELECT jsonb_build_object(
            'type',     'FeatureCollection',
            'features', COALESCE(jsonb_agg(features.feature), '[]'::jsonb)
        )
        FROM (
          SELECT jsonb_build_object(
            'type',       'Feature',
            'id',         id,
            'geometry',   ST_AsGeoJSON(ST_Transform(geom, 4326))::jsonb,
            'properties', jsonb_build_object(
                'name', name,
                'layer', layer
            )
          ) AS feature
          FROM regions
        ) features;
    """)
    
    result = await db.execute(query)
    geojson_data = result.scalar()
    return geojson_data
