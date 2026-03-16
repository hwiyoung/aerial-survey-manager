"""도엽(map sheet) 격자 조회 API."""
import json
import os
import glob
import time
from fastapi import APIRouter, Query, HTTPException, status
from pyproj import Transformer

router = APIRouter(prefix="/sheets", tags=["sheets"])

# ── 좌표 변환기 (EPSG:5179 → WGS84) ──
_to_4326 = Transformer.from_crs("EPSG:5179", "EPSG:4326", always_xy=True)

# ── 메모리 인덱스 (축척별) ──
# 구조: { scale: { "sheets": {mapid: {b5179, b4326, name}}, "loaded": bool } }
_index: dict[int, dict] = {}
_DATA_DIR = os.environ.get("SHEET_DATA_DIR", "/data/storage/../")  # will be resolved

def _find_data_dir() -> str:
    """도엽 GeoJSON 파일이 있는 data 디렉토리를 찾는다."""
    candidates = [
        "/data/data",           # docker volume mount
        "/data",                # fallback
        os.path.join(os.path.dirname(__file__), "..", "..", "..", "data"),  # dev
    ]
    for d in candidates:
        pattern = os.path.join(d, "TN_MAPINDX_*K_5179.geojson")
        if glob.glob(pattern):
            return d
    return candidates[0]


def _load_scale(scale: int) -> dict:
    """GeoJSON 파일에서 bounds만 추출하여 경량 인덱스를 구축한다."""
    data_dir = _find_data_dir()
    filename = f"TN_MAPINDX_{scale // 1000}K_5179.geojson"
    filepath = os.path.join(data_dir, filename)

    if not os.path.exists(filepath):
        return {"sheets": {}, "loaded": False, "count": 0}

    t0 = time.time()
    sheets = {}

    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)

    for feat in data["features"]:
        props = feat["properties"]
        mapid = str(props.get("MAPIDCD_NO", ""))
        name = props.get("MAPID_NM", "")

        # geometry bounds 추출 (Polygon)
        geom = feat["geometry"]
        coords = geom["coordinates"]
        # Polygon: coords[0] = exterior ring
        if geom["type"] == "MultiPolygon":
            ring = coords[0][0]
        else:
            ring = coords[0]

        xs = [p[0] for p in ring]
        ys = [p[1] for p in ring]
        minx, maxx = min(xs), max(xs)
        miny, maxy = min(ys), max(ys)

        # EPSG:5179 → WGS84 변환 (4 corners)
        lon_min, lat_min = _to_4326.transform(minx, miny)
        lon_max, lat_max = _to_4326.transform(maxx, maxy)

        sheets[mapid] = {
            "b5179": (minx, miny, maxx, maxy),
            "b4326": (lat_min, lon_min, lat_max, lon_max),  # (minlat, minlon, maxlat, maxlon)
            "name": name,
        }

    elapsed = time.time() - t0
    print(f"[sheets] Loaded {len(sheets)} sheets for 1:{scale} from {filename} in {elapsed:.1f}s", flush=True)

    return {"sheets": sheets, "loaded": True, "count": len(sheets)}


def _get_index(scale: int) -> dict:
    """축척별 인덱스를 반환 (lazy loading)."""
    if scale not in _index:
        _index[scale] = _load_scale(scale)
    return _index[scale]


def _bbox_intersects(a, b) -> bool:
    """두 bbox가 교차하는지 확인. 형식: (minlat, minlon, maxlat, maxlon)."""
    return not (a[2] < b[0] or a[0] > b[2] or a[3] < b[1] or a[1] > b[3])


@router.get("/scales")
async def get_available_scales():
    """사용 가능한 축척 목록을 반환한다."""
    data_dir = _find_data_dir()
    pattern = os.path.join(data_dir, "TN_MAPINDX_*K_5179.geojson")
    files = glob.glob(pattern)

    scales = []
    for f in sorted(files):
        basename = os.path.basename(f)
        # TN_MAPINDX_5K_5179.geojson → 5
        try:
            k = int(basename.split("_")[2].replace("K", ""))
            scale = k * 1000
            idx = _get_index(scale)
            if idx["loaded"]:
                scales.append({"scale": scale, "label": f"1:{scale:,}", "count": idx["count"]})
        except (IndexError, ValueError):
            continue

    return {"scales": scales}


@router.get("")
async def get_sheets(
    scale: int = Query(..., description="축척 (예: 5000, 1000)"),
    bounds: str = Query(..., description="WGS84 bounds: minlat,minlon,maxlat,maxlon"),
):
    """프로젝트 bounds와 교차하는 도엽 목록을 반환한다."""
    idx = _get_index(scale)
    if not idx["loaded"]:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"1:{scale} 도엽 데이터가 없습니다.",
        )

    try:
        parts = [float(x.strip()) for x in bounds.split(",")]
        if len(parts) != 4:
            raise ValueError
        query_bbox = tuple(parts)  # (minlat, minlon, maxlat, maxlon)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="bounds 형식이 올바르지 않습니다. minlat,minlon,maxlat,maxlon",
        )

    MAX_SHEETS = 200  # 성능을 위해 최대 반환 개수 제한

    results = []
    for mapid, info in idx["sheets"].items():
        if _bbox_intersects(query_bbox, info["b4326"]):
            b = info["b4326"]
            results.append({
                "mapid": mapid,
                "name": info["name"],
                "bounds_wgs84": [
                    [b[0], b[1]],  # [minlat, minlon]
                    [b[2], b[3]],  # [maxlat, maxlon]
                ],
            })
            if len(results) >= MAX_SHEETS:
                break

    truncated = len(results) >= MAX_SHEETS
    return {"sheets": results, "scale": scale, "total": len(results), "truncated": truncated}


@router.get("/search")
async def search_sheet(
    mapid: str = Query(..., description="도엽번호 (MAPIDCD_NO)"),
):
    """도엽번호로 검색하여 해당 도엽의 정보를 반환한다."""
    # 모든 축척에서 검색
    for scale in [1000, 5000]:
        idx = _get_index(scale)
        if not idx["loaded"]:
            continue
        if mapid in idx["sheets"]:
            info = idx["sheets"][mapid]
            b = info["b4326"]
            return {
                "found": True,
                "scale": scale,
                "mapid": mapid,
                "name": info["name"],
                "bounds_wgs84": [
                    [b[0], b[1]],
                    [b[2], b[3]],
                ],
            }

    return {"found": False, "mapid": mapid}
