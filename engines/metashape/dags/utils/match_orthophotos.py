#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
match_orthophotos.py

GDAL 기반: 두 정사영상을 동일 격자/해상도로 정렬한 뒤,
알파 AND로 완전 중첩 영역만 남겨 T1/T2 및 교차 폴리곤을 만듭니다.
각 주요 블록 처리에 tqdm 진행률을 넣었습니다.
"""

import argparse
import math
import os
import shutil
import stat
import tempfile
from typing import Tuple

import numpy as np
from osgeo import gdal, ogr, osr

gdal.UseExceptions()
gdal.SetConfigOption("GDAL_NUM_THREADS", "ALL_CPUS")

DEFAULT_RES = 0.12
DEFAULT_BLOCK = 1024


def _snap_bounds(bounds: Tuple[float, float, float, float], res: float):
    minx, miny, maxx, maxy = bounds
    minx = math.floor(minx / res) * res
    miny = math.floor(miny / res) * res
    maxx = math.ceil(maxx / res) * res
    maxy = math.ceil(maxy / res) * res
    if maxx <= minx or maxy <= miny:
        raise RuntimeError("두 영상의 공통 영역이 없습니다.")
    return minx, miny, maxx, maxy


def _has_alpha(ds: gdal.Dataset) -> bool:
    for i in range(1, ds.RasterCount + 1):
        if ds.GetRasterBand(i).GetColorInterpretation() == gdal.GCI_AlphaBand:
            return True
    return False


def ensure_alpha(src_path: str, tmp_dir: str) -> str:
    ds = gdal.Open(src_path, gdal.GA_ReadOnly)
    if ds is None:
        raise RuntimeError(f"열 수 없음: {src_path}")
    if _has_alpha(ds):
        ds = None
        return src_path
    out = os.path.join(tmp_dir, os.path.basename(src_path))
    gdal.Warp(out, src_path, format="GTiff", dstAlpha=True, multithread=True, warpOptions=["NUM_THREADS=ALL_CPUS"])
    ds = None
    return out


def _transform_bounds(bounds, src_wkt, dst_wkt):
    if src_wkt == dst_wkt:
        return bounds
    src = osr.SpatialReference()
    src.ImportFromWkt(src_wkt)
    dst = osr.SpatialReference()
    dst.ImportFromWkt(dst_wkt)
    tx = osr.CoordinateTransformation(src, dst)
    pts = [
        tx.TransformPoint(bounds[0], bounds[1]),
        tx.TransformPoint(bounds[0], bounds[3]),
        tx.TransformPoint(bounds[2], bounds[1]),
        tx.TransformPoint(bounds[2], bounds[3]),
    ]
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    return min(xs), min(ys), max(xs), max(ys)


def _intersect_bounds(ds_r, ds_t, target_wkt):
    def extent(ds):
        gt = ds.GetGeoTransform()
        minx, maxy = gt[0], gt[3]
        maxx = minx + gt[1] * ds.RasterXSize
        miny = maxy + gt[5] * ds.RasterYSize
        return minx, miny, maxx, maxy

    r_b = _transform_bounds(extent(ds_r), ds_r.GetProjection(), target_wkt)
    t_b = _transform_bounds(extent(ds_t), ds_t.GetProjection(), target_wkt)
    minx = max(r_b[0], t_b[0])
    miny = max(r_b[1], t_b[1])
    maxx = min(r_b[2], t_b[2])
    maxy = min(r_b[3], t_b[3])
    return minx, miny, maxx, maxy


def _safe_remove(path: str):
    if os.path.exists(path):
        os.chmod(path, stat.S_IWRITE)
        os.remove(path)


def _clean_shapefile(shp_path: str):
    base, _ = os.path.splitext(shp_path)
    for ext in (".shp", ".shx", ".dbf", ".prj", ".cpg"):
        _safe_remove(base + ext)


def warp_to_grid(src, dst, bounds, srs_wkt, res):
    gdal.Warp(
        dst,
        src,
        format="GTiff",
        dstSRS=srs_wkt,
        outputBounds=bounds,
        xRes=res,
        yRes=res,
        targetAlignedPixels=True,
        dstAlpha=True,
        multithread=True,
        warpOptions=["NUM_THREADS=ALL_CPUS", "INIT_DEST=0", "UNIFIED_SRC_NODATA=YES"],
        resampleAlg="bilinear",
    )


def create_mask(alpha1, alpha2, out_mask, block=DEFAULT_BLOCK):
    ds1 = gdal.Open(alpha1)
    ds2 = gdal.Open(alpha2)
    band1 = ds1.GetRasterBand(ds1.RasterCount)  # 마지막 밴드를 알파로 가정
    band2 = ds2.GetRasterBand(ds2.RasterCount)

    x_size = ds1.RasterXSize
    y_size = ds1.RasterYSize
    drv = gdal.GetDriverByName("GTiff")
    out_ds = drv.Create(out_mask, x_size, y_size, 1, gdal.GDT_Byte, options=["COMPRESS=LZW", "TILED=YES"])
    out_ds.SetGeoTransform(ds1.GetGeoTransform())
    out_ds.SetProjection(ds1.GetProjection())
    out_band = out_ds.GetRasterBand(1)
    out_band.SetNoDataValue(0)

    for y in range(0, y_size, block):
        rows = block if y + block < y_size else y_size - y
        for x in range(0, x_size, block):
            cols = block if x + block < x_size else x_size - x
            a1 = band1.ReadAsArray(x, y, cols, rows)
            a2 = band2.ReadAsArray(x, y, cols, rows)
            inter = np.logical_and(a1 > 0, a2 > 0).astype(np.uint8)
            out_band.WriteArray(inter, x, y)

    out_band.FlushCache()
    out_ds = None
    ds1 = None
    ds2 = None


def mask_to_shp_keep_largest(mask_tif, shp_out):
    _clean_shapefile(shp_out)
    drv = ogr.GetDriverByName("ESRI Shapefile")
    tmp_path = os.path.splitext(shp_out)[0] + "_tmp.shp"
    _clean_shapefile(tmp_path)
    tmp_vec = drv.CreateDataSource(tmp_path)
    if tmp_vec is None:
        raise RuntimeError(f"임시 셰이프파일을 생성할 수 없습니다: {tmp_path}")
    ds_m = gdal.Open(mask_tif)
    band = ds_m.GetRasterBand(1)
    srs = osr.SpatialReference()
    srs.ImportFromWkt(ds_m.GetProjection())
    tmp_layer = tmp_vec.CreateLayer("tmp", srs, ogr.wkbPolygon)
    tmp_layer.CreateField(ogr.FieldDefn("val", ogr.OFTInteger))
    gdal.Polygonize(band, None, tmp_layer, 0, [], None)
    ds_m = None

    max_area, best_geom = -1, None
    for f in tmp_layer:
        g = f.GetGeometryRef()
        if g:
            a = g.Area()
            if a > max_area:
                max_area = a
                best_geom = g.Clone()
    tmp_vec = None

    if best_geom:
        shell = ogr.Geometry(ogr.wkbPolygon)
        shell.AddGeometry(best_geom.GetGeometryRef(0).Clone())
        best_geom = shell

    ds_out = drv.CreateDataSource(shp_out)
    out_lyr = ds_out.CreateLayer("inter", srs, ogr.wkbPolygon)
    out_lyr.CreateField(ogr.FieldDefn("id", ogr.OFTInteger))
    if best_geom:
        feat = ogr.Feature(out_lyr.GetLayerDefn())
        feat.SetField("id", 1)
        feat.SetGeometry(best_geom)
        out_lyr.CreateFeature(feat)
    ds_out = None
    drv.DeleteDataSource(tmp_path)


def apply_mask(rgba_path, mask_path, out_path, block=DEFAULT_BLOCK):
    src = gdal.Open(rgba_path)
    mask_ds = gdal.Open(mask_path)
    gt = src.GetGeoTransform()
    proj = src.GetProjection()
    x_size, y_size = src.RasterXSize, src.RasterYSize

    drv = gdal.GetDriverByName("GTiff")
    dst = drv.Create(
        out_path,
        x_size,
        y_size,
        4,
        gdal.GDT_Byte,
        options=["COMPRESS=LZW", "TILED=YES", "BIGTIFF=IF_SAFER"],
    )
    dst.SetGeoTransform(gt)
    dst.SetProjection(proj)
    total_rows = math.ceil(y_size / block)
    for y in range(0, y_size, block):
        rows = block if y + block < y_size else y_size - y
        for x in range(0, x_size, block):
            cols = block if x + block < x_size else x_size - x
            # 밴드별로 읽어서 스택
            rgb = np.stack([src.GetRasterBand(i).ReadAsArray(x, y, cols, rows) for i in (1, 2, 3)])
            mask = mask_ds.GetRasterBand(1).ReadAsArray(x, y, cols, rows)
            mask_bool = mask == 1
            if not mask_bool.any():
                rgb[:] = 0
                alpha = np.zeros_like(mask, dtype=np.uint8)
            else:
                rgb[:, ~mask_bool] = 0
                alpha = (mask_bool.astype(np.uint8) * 255).astype(np.uint8)
            # 밴드별로 기록
            for idx, arr in enumerate(rgb, start=1):
                dst.GetRasterBand(idx).WriteArray(arr, xoff=x, yoff=y)
            dst.GetRasterBand(4).WriteArray(alpha, xoff=x, yoff=y)
    dst.FlushCache()
    src = None
    mask_ds = None
    dst = None



def run(ref_path: str, tgt_path: str, outdir: str, res: float = DEFAULT_RES, block: int = DEFAULT_BLOCK):
    os.makedirs(outdir, exist_ok=True)
    t1_dir = os.path.join(outdir, "T1")
    t2_dir = os.path.join(outdir, "T2")
    os.makedirs(t1_dir, exist_ok=True)
    os.makedirs(t2_dir, exist_ok=True)

    tmpdir = tempfile.mkdtemp(prefix="ortho_tmp_")
    try:
        print("알파 확인/생성...")
        ref_a = ensure_alpha(ref_path, tmpdir)
        tgt_a = ensure_alpha(tgt_path, tmpdir)

        ds_r = gdal.Open(ref_a)
        ds_t = gdal.Open(tgt_a)
        target_wkt = ds_r.GetProjection() or ds_t.GetProjection()
        if not target_wkt:
            raise RuntimeError("CRS가 없습니다.")

        ib = _intersect_bounds(ds_r, ds_t, target_wkt)
        bounds = _snap_bounds(ib, res)
        print(f"교차 영역: {bounds}")
        ds_r = ds_t = None

        ref_aligned = os.path.join(tmpdir, "ref_aligned.tif")
        tgt_aligned = os.path.join(tmpdir, "tgt_aligned.tif")
        print("Warp(ref)...")
        warp_to_grid(ref_a, ref_aligned, bounds, target_wkt, res)
        print("Warp(tgt)...")
        warp_to_grid(tgt_a, tgt_aligned, bounds, target_wkt, res)

        mask_tif = os.path.join(tmpdir, "mask.tif")
        print("알파 AND 마스크 생성...")
        create_mask(ref_aligned, tgt_aligned, mask_tif, block=block)

        shp_out = os.path.join(outdir, "intersection.shp")
        print("폴리곤 생성...")
        mask_to_shp_keep_largest(mask_tif, shp_out)

        out_ref = os.path.join(t1_dir, "change_detection.tif")
        out_tgt = os.path.join(t2_dir, "change_detection.tif")
        print("마스크 적용 및 최종 저장...")
        apply_mask(ref_aligned, mask_tif, out_ref, block=block)
        apply_mask(tgt_aligned, mask_tif, out_tgt, block=block)

        print("✔ 완료")
        print(f"  • ref → {out_ref}")
        print(f"  • tgt → {out_tgt}")
        print(f"  • 교집합 폴리곤 → {shp_out}")
        return out_ref, out_tgt, shp_out, bounds
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def parse_args():
    pa = argparse.ArgumentParser(description="두 정사영상의 공통 영역을 동일 GSD로 정렬해 추출합니다.")
    pa.add_argument("--inputs", nargs=2, metavar=("REF", "TGT"), required=True, help="기준 영상과 대상 영상 경로")
    pa.add_argument("--outdir", required=True, help="출력 디렉터리")
    pa.add_argument("--res", type=float, default=DEFAULT_RES, help="출력 해상도(미터). 기본 0.12")
    pa.add_argument(
        "--block-size",
        type=int,
        default=DEFAULT_BLOCK,
        help="블록 처리 크기(픽셀). 큰 값을 주면 디스크 I/O 감소, 메모리 사용 증가",
    )
    return pa.parse_args()


def main(args=None):
    parsed = parse_args() if args is None else parse_args(args)
    ref_path, tgt_path = parsed.inputs
    run(ref_path, tgt_path, parsed.outdir, parsed.res, parsed.block_size)


if __name__ == "__main__":
    main()
