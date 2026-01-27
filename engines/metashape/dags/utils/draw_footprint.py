# 단순 다운샘플 + 1/0 마스크 → 폴리곤화 전용 버전
import argparse
import math
import time
from typing import Optional

import geopandas as gpd
import numpy as np
import rasterio
from rasterio import features
from rasterio.enums import Resampling
from rasterio.windows import Window
from rasterio.windows import transform as window_transform
from affine import Affine
from shapely.geometry import Polygon, MultiPolygon, shape
from shapely.ops import unary_union

def compute_scale(ds, max_pixels: int, user_scale: Optional[int]) -> int:
    if user_scale and user_scale > 1:
        return user_scale
    total = ds.width * ds.height
    if total <= max_pixels:
        return 1
    return max(1, math.ceil(math.sqrt(total / max_pixels)))


def read_downsampled_mask(ds, band: int, scale: int, thresh: float) -> np.ndarray:
    out_height = max(1, math.ceil(ds.height / scale))
    out_width = max(1, math.ceil(ds.width / scale))
    out_shape = (1, out_height, out_width)
    data = ds.read(band, out_shape=out_shape, resampling=Resampling.nearest)
    nd = ds.nodata
    if nd is not None:
        mask = data != nd
    else:
        mask = data > thresh
    mask = np.asarray(mask)
    if mask.ndim == 3:
        mask = mask[0]
    else:
        mask = mask.reshape(out_height, out_width)
    return mask.astype(np.uint8)


def compute_data_window(mask: np.ndarray):
    rows_any = np.any(mask, axis=1)
    cols_any = np.any(mask, axis=0)
    if not rows_any.any() or not cols_any.any():
        return None
    row_idx = np.where(rows_any)[0]
    col_idx = np.where(cols_any)[0]
    row_start, row_stop = row_idx[0], row_idx[-1] + 1
    col_start, col_stop = col_idx[0], col_idx[-1] + 1
    return Window(col_start, row_start, col_stop - col_start, row_stop - row_start)


def exterior_only(geom):
    if isinstance(geom, Polygon):
        return Polygon(geom.exterior)
    if isinstance(geom, MultiPolygon):
        return MultiPolygon([Polygon(p.exterior) for p in geom.geoms if not p.is_empty])
    return geom


def largest_polygon(geom):
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon) and geom.geoms:
        return max(geom.geoms, key=lambda g: g.area)
    return geom


def area_series_with_projection(gdf: gpd.GeoDataFrame):
    crs = gdf.crs
    if crs is None:
        return gdf.geometry.area, "unknown"
    if getattr(crs, "is_projected", False):
        return gdf.geometry.area, crs.to_string()
    try:
        target_crs = gdf.estimate_utm_crs()
    except Exception:
        target_crs = None
    if target_crs is not None:
        area_vals = gdf.to_crs(target_crs).geometry.area
        return area_vals, target_crs.to_string()
    return gdf.geometry.area, f"{crs.to_string()} (geographic)"


def main(ortho, out_geojson, band, thresh, simplify, to_epsg,
         max_pixels, scale_override, connectivity):
    start = time.perf_counter()
    with rasterio.open(ortho) as ds:
        crs = ds.crs
        scale = compute_scale(ds, max_pixels=max_pixels, user_scale=scale_override)
        mask = read_downsampled_mask(ds, band=band, scale=scale, thresh=thresh)
        mask_bool = mask.astype(bool)
        if not mask_bool.any():
            raise RuntimeError("유효한 마스크가 없습니다. (밴드/임계값/다운샘플 확인)")

        window = compute_data_window(mask_bool)
        base_transform = ds.transform * Affine.scale(scale)
        transform = base_transform
        if window is not None:
            r0, c0 = int(window.row_off), int(window.col_off)
            r1, c1 = r0 + int(window.height), c0 + int(window.width)
            mask = mask[r0:r1, c0:c1]
            mask_bool = mask.astype(bool)
            transform = window_transform(window, base_transform)

        shape_iter = features.shapes(
            mask,
            mask=mask_bool,
            transform=transform,
            connectivity=connectivity
        )
        polys = [shape(geom) for geom, _ in shape_iter]
    if not polys:
        raise RuntimeError("유효한 폴리곤이 없습니다. (마스크/임계값/다운샘플 확인)")

    dissolved = unary_union(polys)
    if not dissolved.is_valid:
        dissolved = dissolved.buffer(0)
    outer = exterior_only(dissolved)
    outer_largest = largest_polygon(outer)

    if simplify and simplify > 0:
        outer_largest = outer_largest.simplify(simplify, preserve_topology=True)

    gdf = gpd.GeoDataFrame({"id": [1]}, geometry=[outer_largest], crs=crs)
    area_vals, area_crs_label = area_series_with_projection(gdf)
    gdf["area"] = area_vals

    target_epsg = to_epsg or 4326
    if gdf.crs is not None and target_epsg != gdf.crs.to_epsg():
        gdf = gdf.to_crs(epsg=target_epsg)

    if not out_geojson.lower().endswith((".geojson", ".json")):
        out_geojson += ".geojson"
    gdf.to_file(out_geojson, driver="GeoJSON")

    elapsed = time.perf_counter() - start
    print(f"✅ 완료: {out_geojson}")
    print(f" - 입력 CRS: {crs}")
    print(f" - 다운샘플 배율: x{scale} (원본 {ds.width}x{ds.height} -> {mask.shape[1]}x{mask.shape[0]})")
    print(f" - 면적 계산 CRS: {area_crs_label}")
    print(f" - 총 소요시간: {elapsed:.2f}초")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="다운샘플 + 1/0 마스크 후 폴리곤화")
    ap.add_argument("ortho", help="입력 정사영상(.tif)")
    ap.add_argument("out", help="출력 GeoJSON(.geojson/.json)")
    ap.add_argument("--band", type=int, default=1, help="사용할 밴드(기본 1)")
    ap.add_argument("--thresh", type=float, default=0.0, help="nodata 미지정 시 0보다 큰 값을 1로 간주")
    ap.add_argument("--simplify", type=float, default=None, help="경계 단순화 허용오차(데이터 CRS 단위)")
    ap.add_argument("--to-epsg", type=int, default=4326, help="저장 전 EPSG로 재투영(기본 4326)")
    ap.add_argument("--max-pixels", type=int, default=10_000_000, help="다운샘플 기준 최대 픽셀 수(가로*세로)")
    ap.add_argument("--scale", dest="scale_override", type=int, default=None, help="강제 다운샘플 배율(예: 4면 가로/세로 1/4)")
    ap.add_argument("--connectivity", type=int, choices=[4, 8], default=8, help="마스크 연결성 (4 또는 8)")
    args = ap.parse_args()

    main(
        args.ortho, args.out, args.band, args.thresh,
        args.simplify, args.to_epsg,
        max_pixels=args.max_pixels, scale_override=args.scale_override,
        connectivity=args.connectivity
    )
