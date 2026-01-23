from typing import Optional

# Region definitions matching frontend koreaRegions.js
# Each region is defined by a bounding box [min_lon, min_lat, max_lon, max_lat]
KOREA_REGIONS = {
    "gyeonggi": {
        "name": "경기권역",
        "bbox": [126.3, 36.9, 127.9, 38.0]
    },
    "chungcheong": {
        "name": "충청권역",
        "bbox": [126.3, 35.9, 128.0, 36.9]
    },
    "gangwon": {
        "name": "강원권역",
        "bbox": [127.9, 37.0, 129.5, 38.5]
    },
    "jeolla": {
        "name": "전라권역",
        "bbox": [126.0, 34.0, 127.5, 36.0]
    },
    "gyeongsang": {
        "name": "경상권역",
        "bbox": [127.5, 34.5, 130.0, 37.0]
    }
}

def get_region_for_point(lon: float, lat: float) -> Optional[str]:
    """Determine the region name for a given longitude and latitude."""
    for region_id, info in KOREA_REGIONS.items():
        min_lon, min_lat, max_lon, max_lat = info["bbox"]
        if min_lon <= lon <= max_lon and min_lat <= lat <= max_lat:
            return info["name"]
    return None

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
