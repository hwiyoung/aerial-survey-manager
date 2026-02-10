from typing import Optional, Union
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

# Region definitions - FALLBACK only (prefer using get_region_for_point_db)
# DB regions 테이블의 8개 권역과 이름을 일치시킴
# Each region is defined by a bounding box [min_lon, min_lat, max_lon, max_lat]
KOREA_REGIONS = {
    "sudogwon_north": {
        "name": "수도권북부 권역",
        "bbox": [126.3, 37.5, 127.9, 38.0]
    },
    "sudogwon_south": {
        "name": "수도권남부 권역",
        "bbox": [126.3, 36.9, 127.9, 37.5]
    },
    "gangwon": {
        "name": "강원 권역",
        "bbox": [127.9, 37.0, 129.5, 38.5]
    },
    "chungcheong": {
        "name": "충청 권역",
        "bbox": [126.3, 35.9, 128.0, 36.9]
    },
    "jeolla_east": {
        "name": "전라동부 권역",
        "bbox": [126.8, 34.5, 127.5, 36.0]
    },
    "jeolla_west": {
        "name": "전라서부 권역",
        "bbox": [126.0, 34.0, 126.8, 36.0]
    },
    "gyeongbuk": {
        "name": "경북 권역",
        "bbox": [127.5, 35.8, 130.0, 37.0]
    },
    "gyeongnam": {
        "name": "경남 권역",
        "bbox": [127.5, 34.5, 129.5, 35.8]
    }
}

def get_region_for_point(lon: float, lat: float) -> Optional[str]:
    """Determine the region name for a given longitude and latitude (FALLBACK - uses hardcoded bboxes)."""
    for region_id, info in KOREA_REGIONS.items():
        min_lon, min_lat, max_lon, max_lat = info["bbox"]
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return info["name"]
    return None


async def get_region_for_point_db(db: AsyncSession, lon: float, lat: float) -> Optional[str]:
    """Determine the region name using PostGIS spatial query against regions table."""
    try:
        # Query regions table using ST_Contains
        # Regions are stored in EPSG:5179, so we transform the point
        result = await db.execute(
            text("""
                SELECT r.layer
                FROM regions r
                WHERE ST_Contains(
                    ST_Transform(r.geom, 4326),
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )
                LIMIT 1
            """),
            {"lon": lon, "lat": lat}
        )
        row = result.fetchone()
        if row:
            return row[0]
    except Exception as e:
        # Log error but don't fail - fall back to hardcoded regions
        import logging
        logging.warning(f"PostGIS region query failed: {e}")

    # Fallback to hardcoded bounding boxes
    return get_region_for_point(lon, lat)


def get_region_for_point_sync(db: Session, lon: float, lat: float) -> Optional[str]:
    """Determine the region name using PostGIS spatial query (sync version for Celery workers)."""
    try:
        result = db.execute(
            text("""
                SELECT r.layer
                FROM regions r
                WHERE ST_Contains(
                    ST_Transform(r.geom, 4326),
                    ST_SetSRID(ST_MakePoint(:lon, :lat), 4326)
                )
                LIMIT 1
            """),
            {"lon": lon, "lat": lat}
        )
        row = result.fetchone()
        if row:
            return row[0]
    except Exception as e:
        import logging
        logging.warning(f"PostGIS region query failed: {e}")

    # Fallback to hardcoded bounding boxes
    return get_region_for_point(lon, lat)


def extract_center_from_wkt(wkt_polygon: str) -> tuple[Optional[float], Optional[float]]:
    """Extract center point (lon, lat) from a WKT Polygon string."""
    try:
        # Example: SRID=4326;POLYGON((lon1 lat1, lon2 lat2, ...))
        # This is a very simple parser to avoid dependencies like shapely
        import re
        coords_str = re.search(r'\(\((.+)\)\)', wkt_polygon)
        if not coords_str:
            return None, None
            
        coords = coords_str.group(1).split(',')
        lons = []
        lats = []
        for pt in coords:
            parts = pt.strip().split(' ')
            if len(parts) >= 2:
                lons.append(float(parts[0]))
                lats.append(float(parts[1]))
        
        if not lons or not lats:
            return None, None
            
        return sum(lons) / len(lons), sum(lats) / len(lats)
    except Exception:
        return None, None
