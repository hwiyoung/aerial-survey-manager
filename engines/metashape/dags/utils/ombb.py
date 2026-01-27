#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Oriented Minimum Bounding Box (OMBB) outside QGIS.

- Per-feature OMBB or grouped OMBB (by attribute).
- Computes width, height, angle (deg), area (m^2).
- Automatically reprojects to metric CRS if needed.

Usage:
  python ombb.py INPUT [-l LAYER] -o OUTPUT [--group-field COL]
                       [--metric-crs EPSG:XXXX] [--keep-crs]
"""

import argparse, math, os, sys
import geopandas as gpd
from shapely.geometry import Polygon
from shapely.ops import unary_union
from pyproj import CRS

def pick_metric_crs(gdf: gpd.GeoDataFrame, user_epsg: str | None) -> CRS:
    if user_epsg:
        return CRS.from_user_input(user_epsg)
    crs = gdf.crs
    if crs is None:
        # fallback: assume data is already metric-less; ask user to pass --metric-crs
        raise ValueError("Input has no CRS. Please supply --metric-crs EPSG:XXXX.")
    crs = CRS.from_user_input(crs)
    if crs.is_geographic:
        # Heuristic: 한국 사용이라면 5179(UTM-K), 그렇지 않으면 중심경도 기준 UTM
        try:
            cx, cy = gdf.geometry.unary_union.centroid.x, gdf.geometry.unary_union.centroid.y
        except Exception:
            cx, cy = 127.0, 37.5  # Korea-ish fallback
        # Korea default
        try:
            return CRS.from_epsg(5179)
        except Exception:
            # Generic UTM by longitude
            zone = int((cx + 180) // 6) + 1
            epsg = 32600 + zone if cy >= 0 else 32700 + zone
            return CRS.from_epsg(epsg)
    return crs

def minimum_rotated_rectangle_safe(geom):
    try:
        return geom.minimum_rotated_rectangle
    except Exception:
        # e.g., empty/invalid
        return None

def ensure_polygonish(geom):
    if geom.is_empty:
        return None
    gtype = geom.geom_type
    if gtype in ("Polygon", "MultiPolygon"):
        return geom
    # For points/lines, use convex hull
    hull = geom.convex_hull
    if hull.is_empty or hull.area == 0:
        return None
    return hull

def rect_width_height_angle(rect: Polygon):
    """
    Given a shapely Polygon representing the min rotated rectangle (4-point ring),
    return width, height, angle_deg (direction of the long edge, in degrees, -180~180).
    """
    if rect is None or rect.is_empty:
        return 0.0, 0.0, 0.0
    # exterior coords; last point duplicates the first
    coords = list(rect.exterior.coords)
    if len(coords) < 5:
        return 0.0, 0.0, 0.0

    pts = coords[:-1]
    # build edges (p0->p1, p1->p2, p2->p3, p3->p0)
    edges = [(pts[i], pts[(i+1) % 4]) for i in range(4)]

    def dist(a, b): return math.hypot(b[0] - a[0], b[1] - a[1])
    lengths = [dist(a, b) for a, b in edges]

    # width = shorter edge, height = longer edge
    w = min(lengths)
    h = max(lengths)

    # angle from the longer edge (in degrees, atan2(dy,dx))
    idx_long = lengths.index(h)
    a, b = edges[idx_long]
    angle = math.degrees(math.atan2(b[1]-a[1], b[0]-a[0]))
    # normalize to [-90, 90) if you prefer; keeping [-180,180) here
    return float(w), float(h), float(angle)

def dissolve_by(gdf: gpd.GeoDataFrame, field: str) -> gpd.GeoDataFrame:
    # dissolve keeps geometry only; preserve the group value in a new index
    out = gdf[[field, "geometry"]].dissolve(by=field, as_index=False)
    return out

def compute_ombb(gdf: gpd.GeoDataFrame, group_field: str | None):
    rows = []
    src = gdf.copy()
    if group_field:
        src = dissolve_by(src, group_field)

    for idx, row in src.iterrows():
        geom = ensure_polygonish(row.geometry)
        if geom is None or geom.is_empty:
            continue
        rect = minimum_rotated_rectangle_safe(geom)
        if rect is None or rect.is_empty:
            continue

        w, h, ang = rect_width_height_angle(rect)
        area = rect.area
        props = {}
        if group_field:
            props[group_field] = row[group_field]
        else:
            # keep original index as an id if available
            props["src_id"] = str(idx)

        for col in ["CLS_ID","CONF"]:
            if col in row:
                props[col] = row[col]

        props.update({
            "width": w,
            "height": h,
            "angle_deg": ang,
            "AREA": area
        })
        rows.append((rect, props))

    if not rows:
        return gpd.GeoDataFrame(columns=(["src_id"] if not group_field else [group_field]) +
                                           ["width","height","angle_deg","area_m2","geometry"],
                                geometry="geometry", crs=gdf.crs)
    geoms, data = zip(*rows)
    out = gpd.GeoDataFrame(list(data), geometry=list(geoms), crs=gdf.crs)
    return out

def main():
    
    ap = argparse.ArgumentParser(description="Compute Oriented Minimum Bounding Boxes (outside QGIS).")
    ap.add_argument("input", help="Input vector file (SHP, GPKG, GeoJSON, etc.)")
    ap.add_argument("-l", "--layer", help="Layer name (for GPKG/etc.)")
    ap.add_argument("-o", "--output", required=True, help="Output path (SHP/GPKG/GeoJSON, etc.)")
    ap.add_argument("--group-field", help="Group field to dissolve by, then compute one OBB per group")
    ap.add_argument("--metric-crs", help="Metric CRS to use for geometry calculations (e.g., EPSG:5179).")
    ap.add_argument("--keep-crs", action="store_true",
                    help="Keep output in the metric CRS (default: reproject back to input CRS).")
    args = ap.parse_args()


    # Validate input/output
    if not os.path.exists(args.input):
        print(f"Input file does not exist: {args.input}", file=sys.stderr)
        sys.exit(1)
    if not args.output:
        print("Output path is required.", file=sys.stderr)
        sys.exit(1)
    # 1) Load
    gdf = gpd.read_file(args.input, layer=args.layer) if args.layer else gpd.read_file(args.input)
    if gdf.empty:
        print("No features found.", file=sys.stderr)
        return
    if gdf.geometry.is_empty.all():
        print("All geometries are empty.", file=sys.stderr)
        return 

    # 2) Select metric CRS for computation
    in_crs = gdf.crs
    metric_crs = pick_metric_crs(gdf, args.metric_crs)
    work = gdf.to_crs(metric_crs)

    # 3) Compute OMBB (per-feature or per-group)
    out = compute_ombb(work, args.group_field)

    # 4) Reproject back to input CRS unless --keep-crs
    if not args.keep_crs and in_crs is not None:
        out = out.to_crs(in_crs)
    elif not args.keep_crs and in_crs is None:
        # If input had no CRS, keep metric CRS to avoid losing units.
        pass

    # 5) Save
    # Driver inferred by extension: .gpkg -> GPKG, .geojson/.json -> GeoJSON, .shp -> ESRI Shapefile
    out.to_file(args.output, driver=None)
    print(f"Saved: {args.output}  ({len(out)} OBB features)")

if __name__ == "__main__":
    main()