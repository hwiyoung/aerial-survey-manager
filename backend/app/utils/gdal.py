"""Shared GDAL utilities for GeoTIFF inspection."""
import json
import logging
import re
import subprocess
from typing import Optional

logger = logging.getLogger(__name__)


def run_gdalinfo(file_path: str) -> Optional[dict]:
    """Run gdalinfo -json and return parsed JSON, or None on failure."""
    try:
        result = subprocess.run(
            ["gdalinfo", "-json", file_path],
            capture_output=True, text=True, check=True,
        )
        return json.loads(result.stdout)
    except (subprocess.CalledProcessError, json.JSONDecodeError) as e:
        logger.warning("gdalinfo failed for %s: %s", file_path, e)
        return None


def extract_bounds_wkt(file_path: str) -> Optional[str]:
    """Extract WGS84 bounding box from a GeoTIFF as EWKT Polygon.

    Returns an EWKT string like 'SRID=4326;POLYGON((lon1 lat1, ...))' or None.
    """
    data = run_gdalinfo(file_path)
    if not data:
        return None

    try:
        extent = data.get("wgs84Extent")
        if extent and extent.get("type") == "Polygon":
            coords = extent.get("coordinates", [[]])[0]
            if len(coords) >= 4:
                wkt_points = [f"{pt[0]} {pt[1]}" for pt in coords]
                if wkt_points[0] != wkt_points[-1]:
                    wkt_points.append(wkt_points[0])
                return f"SRID=4326;POLYGON(({', '.join(wkt_points)}))"
    except Exception as e:
        logger.warning("Failed to extract bounds from %s: %s", file_path, e)
    return None


def extract_gsd_and_crs(file_path: str) -> tuple[Optional[float], str]:
    """Extract GSD (meters/pixel) and CRS from a GeoTIFF.

    Returns (gsd_meters, epsg_string).  gsd_meters may be None.
    epsg_string is like 'EPSG:5186' or 'Unknown'.
    """
    data = run_gdalinfo(file_path)
    if not data:
        return None, "Unknown"

    # CRS
    source_wkt = (
        data.get("coordinateSystem", {}).get("wkt", "")
        or data.get("stac", {}).get("proj:wkt2", "")
    )
    epsg_match = re.search(r'ID\["EPSG",(\d+)\]', source_wkt)
    source_crs = f"EPSG:{epsg_match.group(1)}" if epsg_match else "Unknown"

    # GSD (pixel size in CRS units)
    geo_transform = data.get("geoTransform", [])
    if len(geo_transform) >= 2:
        pixel_size = abs(geo_transform[1])
        return pixel_size, source_crs

    return None, source_crs
