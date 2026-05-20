"""TIFF integrity checks for source aerial images."""
from __future__ import annotations

import os
import json
import subprocess
from pathlib import Path
from typing import Any


TIFF_EXTENSIONS = {".tif", ".tiff"}
SERIOUS_GDAL_WARNING_KEYWORDS = ("not a jpeg", "bogus", "corrupt", "truncat", "invalid")
GDALINFO_TIMEOUT_SECONDS = 60
GDAL_READ_TIMEOUT_SECONDS = 90
GDAL_OVERVIEW_SAMPLE_SIZE = 256
GDAL_FULL_IMAGE_SAMPLE_SIZE = 128


def is_tiff_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in TIFF_EXTENSIONS


def check_tiff_integrity(filepath: str | Path) -> dict[str, Any]:
    """Read representative TIFF blocks and overviews to catch libtiff/GDAL errors."""
    path = str(filepath)
    result: dict[str, Any] = {
        "file": path,
        "status": "OK",
        "size_mb": 0,
        "bands": 0,
        "width": 0,
        "height": 0,
        "overviews_expected": 0,
        "overviews_ok": 0,
        "errors": [],
    }

    if not is_tiff_path(path):
        result["status"] = "SKIPPED"
        return result

    try:
        result["size_mb"] = round(os.path.getsize(path) / (1024 * 1024), 1)
    except OSError:
        result["status"] = "ERROR"
        result["errors"].append("파일 크기를 읽을 수 없음")
        return result

    try:
        from osgeo import gdal
    except ImportError as exc:
        result["errors"].append(f"Python GDAL 바인딩을 사용할 수 없음: {exc}")
        return _check_with_gdalinfo(path, result)

    gdal.UseExceptions()
    collected_warnings: list[str] = []

    def _err_handler(_err_class, _err_num, err_msg):
        collected_warnings.append(str(err_msg))

    gdal.PushErrorHandler(_err_handler)
    ds = None
    try:
        ds = gdal.Open(path, gdal.GA_ReadOnly)
        if ds is None:
            result["status"] = "ERROR"
            result["errors"].append("GDAL로 파일을 열 수 없음")
            return result

        result["bands"] = ds.RasterCount
        result["width"] = ds.RasterXSize
        result["height"] = ds.RasterYSize

        for band_index in range(1, ds.RasterCount + 1):
            band = ds.GetRasterBand(band_index)
            if band is None:
                result["errors"].append(f"Band {band_index}: 밴드를 가져올 수 없음")
                continue

            block_xsize, block_ysize = band.GetBlockSize()
            try:
                band.ReadAsArray(
                    0,
                    0,
                    min(block_xsize, band.XSize),
                    min(block_ysize, band.YSize),
                )
                last_x = max(0, band.XSize - block_xsize)
                last_y = max(0, band.YSize - block_ysize)
                band.ReadAsArray(
                    last_x,
                    last_y,
                    min(block_xsize, band.XSize - last_x),
                    min(block_ysize, band.YSize - last_y),
                )
            except Exception as exc:
                result["errors"].append(f"Band {band_index} 메인이미지 읽기 실패: {exc}")

            overview_count = band.GetOverviewCount()
            if band_index == 1:
                result["overviews_expected"] = overview_count

            for overview_index in range(overview_count):
                overview = band.GetOverview(overview_index)
                if overview is None:
                    result["errors"].append(
                        f"Band {band_index} Overview {overview_index}: 가져올 수 없음"
                    )
                    continue
                try:
                    overview.ReadAsArray()
                    if band_index == 1:
                        result["overviews_ok"] += 1
                except Exception as exc:
                    result["errors"].append(
                        f"Band {band_index} Overview {overview_index} "
                        f"({overview.XSize}x{overview.YSize}) 읽기 실패: {exc}"
                    )

        for warning in collected_warnings:
            warning_text = warning.strip()
            if any(keyword in warning_text.lower() for keyword in SERIOUS_GDAL_WARNING_KEYWORDS):
                result["errors"].append(f"GDAL 경고: {warning_text}")
    except Exception as exc:
        result["status"] = "ERROR"
        result["errors"].append(f"예외 발생: {exc}")
    finally:
        ds = None
        gdal.PopErrorHandler()

    if result["errors"]:
        result["status"] = "CORRUPT" if result["status"] == "OK" else result["status"]

    return result


def _check_with_gdalinfo(path: str, result: dict[str, Any]) -> dict[str, Any]:
    """Fallback integrity check using the GDAL CLI available in backend images."""
    try:
        completed = subprocess.run(
            ["gdalinfo", "-json", path],
            check=False,
            capture_output=True,
            text=True,
            timeout=GDALINFO_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        result["status"] = "ERROR"
        result["errors"].append("gdalinfo 실행 파일을 찾을 수 없음")
        return result
    except subprocess.TimeoutExpired:
        result["status"] = "ERROR"
        result["errors"].append("gdalinfo 메타데이터 검사 타임아웃")
        return result
    except Exception as exc:
        result["status"] = "ERROR"
        result["errors"].append(f"gdalinfo 실행 실패: {exc}")
        return result

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        result["status"] = "ERROR"
        result["errors"].append(stderr or f"gdalinfo 종료 코드 {completed.returncode}")
        return result

    try:
        info = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        result["status"] = "ERROR"
        result["errors"].append(f"gdalinfo JSON 파싱 실패: {exc}")
        return result

    size = info.get("size") or []
    if len(size) >= 2:
        result["width"] = size[0]
        result["height"] = size[1]

    bands = info.get("bands") or []
    result["bands"] = len(bands)
    if bands:
        overviews = bands[0].get("overviews") or []
        result["overviews_expected"] = len(overviews)

    result["errors"] = [
        error for error in result["errors"]
        if not str(error).startswith("Python GDAL 바인딩을 사용할 수 없음")
    ]

    _append_serious_gdal_warnings(result, stderr)

    if result["width"] and result["height"]:
        _run_gdal_read_samples(path, result, bands)

    if result["errors"]:
        result["status"] = "CORRUPT"

    return result


def _append_serious_gdal_warnings(
    result: dict[str, Any],
    stderr: str | None,
    prefix: str = "GDAL 경고",
) -> None:
    for warning in (stderr or "").splitlines():
        warning_text = warning.strip()
        if any(keyword in warning_text.lower() for keyword in SERIOUS_GDAL_WARNING_KEYWORDS):
            result["errors"].append(f"{prefix}: {warning_text}")


def _run_gdal_read_samples(path: str, result: dict[str, Any], bands: list[dict[str, Any]]) -> None:
    """Read small main-image and overview samples without scanning the whole TIFF."""
    width = int(result.get("width") or 0)
    height = int(result.get("height") or 0)
    if width <= 0 or height <= 0:
        return

    first_band = bands[0] if bands else {}
    block_size = first_band.get("block") or []
    block_x = int(block_size[0]) if len(block_size) >= 1 and block_size[0] else min(width, 512)
    block_y = int(block_size[1]) if len(block_size) >= 2 and block_size[1] else min(height, 512)
    block_x = max(1, min(width, block_x))
    block_y = max(1, min(height, block_y))

    sample_id = f"{os.getpid()}-{abs(hash(path))}"
    windows = [
        ("메인이미지 시작 블록", 0, 0, block_x, block_y),
        (
            "메인이미지 끝 블록",
            max(0, width - block_x),
            max(0, height - block_y),
            block_x,
            block_y,
        ),
    ]

    for label, xoff, yoff, xsize, ysize in windows:
        _run_gdal_translate_sample(
            path,
            result,
            label,
            [
                "-srcwin",
                str(xoff),
                str(yoff),
                str(xsize),
                str(ysize),
            ],
            f"/vsimem/tiff-integrity-{sample_id}-main-{xoff}-{yoff}",
        )

    _run_gdal_translate_sample(
        path,
        result,
        "전체 이미지 축소",
        [
            "-r",
            "nearest",
            "-outsize",
            str(GDAL_FULL_IMAGE_SAMPLE_SIZE),
            "0",
        ],
        f"/vsimem/tiff-integrity-{sample_id}-full",
    )

    overviews = first_band.get("overviews") or []
    overviews_ok = 0
    for overview_index, _overview in enumerate(overviews):
        before_count = len(result["errors"])
        _run_gdal_translate_sample(
            path,
            result,
            f"Overview {overview_index}",
            [
                "-ovr",
                str(overview_index),
                "-outsize",
                str(GDAL_OVERVIEW_SAMPLE_SIZE),
                "0",
            ],
            f"/vsimem/tiff-integrity-{sample_id}-ovr-{overview_index}",
        )
        if len(result["errors"]) == before_count:
            overviews_ok += 1
    result["overviews_ok"] = overviews_ok


def _run_gdal_translate_sample(
    path: str,
    result: dict[str, Any],
    label: str,
    options: list[str],
    output_path: str,
) -> None:
    try:
        completed = subprocess.run(
            ["gdal_translate", "-q", "-of", "MEM", *options, path, output_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=GDAL_READ_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        result["status"] = "ERROR"
        result["errors"].append("gdal_translate 실행 파일을 찾을 수 없음")
        return
    except subprocess.TimeoutExpired:
        result["status"] = "ERROR"
        result["errors"].append(f"{label} 읽기 검사 타임아웃")
        return
    except Exception as exc:
        result["status"] = "ERROR"
        result["errors"].append(f"{label} 읽기 검사 실패: {exc}")
        return

    stderr = (completed.stderr or "").strip()
    if completed.returncode != 0:
        before_count = len(result["errors"])
        _append_serious_gdal_warnings(result, stderr, prefix=f"{label} GDAL 오류")
        if len(result["errors"]) == before_count:
            first_line = next((line.strip() for line in stderr.splitlines() if line.strip()), "")
            result["errors"].append(
                f"{label} 읽기 실패: {first_line or f'종료 코드 {completed.returncode}'}"
            )
        return

    _append_serious_gdal_warnings(result, stderr, prefix=f"{label} GDAL 경고")


def summarize_tiff_errors(result: dict[str, Any], max_errors: int = 3) -> str:
    errors = result.get("errors") or []
    if not errors:
        return ""
    visible = [str(error) for error in errors[:max_errors]]
    if len(errors) > max_errors:
        visible.append(f"외 {len(errors) - max_errors}건")
    return " | ".join(visible)
