# -*- coding: utf-8 -*-
from __future__ import annotations
import re, shutil, logging, time
from pathlib import Path
from typing import List, Dict, Tuple, Optional, Any
from datetime import datetime, timedelta
import json
import os


import requests
import pendulum
from airflow.decorators import dag, task
from airflow.models import Variable
# from utils.digital_map import create_thumbnail
import subprocess


# ───────────────────── 설정
INPUT_DIR    = Path(os.getenv("GEO_INPUT_DIR", "/app/.uploads/data"))
PROJECT_ROOT = Path(os.getenv("GEO_PROJECT_ROOT", "/app/.inputs/data"))
API_URL      = os.getenv("GEO_API_URL", "http://host.docker.internal:3000/resources")
PLATFORM     = os.getenv("GEO_PLATFORM", "항공")
TZ = pendulum.timezone("Asia/Seoul")

SHP_SIDE_EXTS = [".shp", ".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".qix", ".shp.xml",".qmd",".geojson"]
RE_TIFF = re.compile(r"^(?P<loc>[^_]+)_(?P<ym>\d{6,8})_(?P<gsd>\d+(?:\.\d+)?)\s*cm\.(?:tif|tiff)$", re.IGNORECASE)
RE_SHP  = re.compile(r"^(?P<loc>[^_]+)_(?P<ym>\d{6,8})_(?P<crs>[^_]+)_(?P<scale>\d+)\.shp$", re.IGNORECASE)

# ───────────────────── 유틸
def parse_ym_to_range(ym: str) -> Tuple[Optional[str], Optional[str]]:
    try:
        if len(ym) == 6:
            y, m = int(ym[:4]), int(ym[4:6])
            s = pendulum.datetime(y, m, 1, tz=TZ)   # ← 이걸로!
            e = s.end_of('month')                   # v3 안전: end_of 사용
            return s.to_iso8601_string(), e.to_iso8601_string()

        if len(ym) == 8:
            y, m, d = int(ym[:4]), int(ym[4:6]), int(ym[6:8])
            s = pendulum.datetime(y, m, d, tz=TZ)   # ← 이걸로!
            e = s.end_of('day')                     # 23:59:59.999999+09:00
            # 필요하면 초단위 끝으로 맞추기:
            e = e.replace(microsecond=0)            # 23:59:59
            return s.to_iso8601_string(), e.to_iso8601_string()

    except Exception:
        logging.exception("촬영/제작 연월 파싱 실패")
    return None, None

def collect_shp_set(shp_path: Path) -> List[Path]:
    "SHP 본체 기준 동반 파일 전체를 모은다."
    base = shp_path.with_suffix("")
    return [Path(f"{base}{ext}") for ext in SHP_SIDE_EXTS if Path(f"{base}{ext}").exists()]

def is_locked(p: Path, wait_sec: float = 1.0) -> bool:
    "파일의 크기/mtime을 wait_sec 후 재측정해 변하면 업로드 중으로 본다."
    try:
        s1 = p.stat()
        time.sleep(wait_sec)
        s2 = p.stat()
        return (s1.st_size, s1.st_mtime) != (s2.st_size, s2.st_mtime)
    except FileNotFoundError:
        return True

def any_locked(paths: List[Path], wait_sec: float = 1.0) -> bool:
    "여러 파일 중 하나라도 업로드 중이면 True."
    return any(is_locked(x, wait_sec) for x in paths)

def move_with_timestamp(srcs: List[Path], target_dir: Path, ts: str,atype) -> List[Path]:
    "여러 파일을 대상 폴더로 이동하며 _타임스탬프를 부착한다."
    target_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    for f in srcs:
        dest = target_dir / f"{f.stem}_{ts}{f.suffix}"
        shutil.move(str(f), str(dest))
        if atype == "image":
            create_thumbnail(str(dest))
        moved.append(dest)
    return moved

def create_thumbnail(input_tif, width_px=256, height_px=256):
    from osgeo import gdal
    import os
    
    thumbnail_name = input_tif.replace('.tif', '_thumbnail.png')


    """6. COG에서 썸네일 생성"""
    ds = gdal.Open(input_tif)
    if ds is None:
        raise FileNotFoundError(f"파일을 열 수 없습니다: {input_tif}")

    # 썸네일 생성
    gdal.Translate(
        thumbnail_name,
        ds,
        format='PNG',
        width=width_px,
        height=height_px
    )

    ds = None


COG_CREATION_OPTS = [
    "COMPRESS=LZW",
    "OVERVIEWS=IGNORE_EXISTING",
]


def is_cog_tiff(tif_path: Union[str, Path]) -> bool:
    """
    Check the GeoTIFF validity and layout to confirm COG compliance.
    Reflects logic from rio_cogeo.cogeo.cog_validate using osgeo.gdal.
    """
    try:
        from osgeo import gdal
    except ImportError:
        logging.exception("GDAL import 실패")
        return False

    try:
        # GDAL Info를 JSON 포맷으로 가져와서 메타데이터와 구조를 파싱
        info = gdal.Info(str(tif_path), format='json')
    except RuntimeError:
        logging.exception("gdal.Info 호출 실패: %s", tif_path)
        return False

    if not info:
        return False

    # 1. Driver Check (rio_cogeo: if not src.driver == "GTiff")
    if info.get('driverShortName') != 'GTiff':
        logging.warning("Not a GeoTIFF driver")
        return False

    # 2. External Overviews Check (rio_cogeo: .ovr in src.files)
    # COG는 오버뷰가 내장되어야 하므로 .ovr 파일이 별도로 존재하면 안 됨
    files = info.get('files', [])
    if any(f.endswith('.ovr') for f in files):
        logging.warning("External overview (.ovr) file found")
        return False

    # 3. Tiling Check (rio_cogeo: src.is_tiled)
    # 512x512보다 큰 이미지는 타일링이 되어 있어야 함
    size = info.get('size', [])  # [width, height]
    if size and len(size) == 2:
        width, height = size
        # 이미지가 작으면 타일링이 필수는 아니지만, 보통 COG는 타일링됨
        if width > 512 or height > 512:
            bands = info.get('bands', [])
            if bands:
                # 첫 번째 밴드의 블록 크기 확인
                block_size = bands[0].get('block', [])  # [w, h]
                # 블록 너비가 이미지 너비와 같으면 Strip 방식이므로 Tiled가 아님
                if block_size and block_size[0] == width:
                    logging.warning("File is not tiled (Striped layout)")
                    return False

    # 4. Layout & IFD Check (rio_cogeo: IFD_OFFSET checks)
    # rio_cogeo는 바이트 오프셋을 직접 계산하지만, GDAL 3.1+에서는 
    # 올바른 COG 구조(IFD가 데이터 앞에 위치 등)를 가질 경우 'LAYOUT=COG' 메타데이터를 생성함.
    metadata = info.get('metadata', {})
    image_structure = metadata.get('IMAGE_STRUCTURE', {})
    
    if image_structure.get('LAYOUT') != 'COG':
        logging.warning("LAYOUT metadata is not 'COG'")
        return False

    return True


def convert_to_cog_in_place(tif_path: Path) -> Path:
    "Create a Cloud Optimized GeoTIFF if the input is not already COG."
    if is_cog_tiff(tif_path):
        return tif_path

    try:
        from osgeo import gdal
    except ImportError as exc:
        logging.exception("GDAL import 실패")
        raise

    if not tif_path.exists():
        raise FileNotFoundError(f"COG 변환 실패, 파일을 찾을 수 없습니다: {tif_path}")

    tmp_path = tif_path.parent / f"{tif_path.stem}_cog_tmp{tif_path.suffix}"
    if tmp_path.exists():
        tmp_path.unlink()

    cog_ds = None
    try:
        cog_ds = gdal.Translate(
            str(tmp_path),
            str(tif_path),
            format='COG',
            creationOptions=COG_CREATION_OPTS,
        )
    except RuntimeError:
        logging.exception("COG 변환 실패: %s", tif_path)
        if tmp_path.exists():
            tmp_path.unlink()
        raise
    finally:
        cog_ds = None

    backup_path = tif_path.parent / f"{tif_path.stem}_orig{tif_path.suffix}"
    if backup_path.exists():
        backup_path.unlink()

    tif_path.rename(backup_path)
    try:
        tmp_path.rename(tif_path)
    except Exception:
        backup_path.rename(tif_path)
        logging.exception("COG 변환 파일 교체 실패, 원본 복구: %s", tif_path)
        raise
    else:
        backup_path.unlink()

    logging.info("COG 변환 완료: %s", tif_path)
    return tif_path


def post_with_retry(payload: dict, tries: int = 3, timeout: int = 10):
    "API에 POST를 재시도하며 전송한다."
    last = None
    for i in range(1, tries + 1):
        try:
            r = requests.post(API_URL, json=payload, timeout=timeout)
            return r.status_code, r.text
        except Exception as e:
            last = e
    raise last

def update_with_retry(payload: dict, tries: int = 3, timeout: int = 10, id: str=None):
    "API에 PUT/PATCH 요청을 재시도하며 전송한다."
    last = None
    for i in range(1, tries + 1):
        try:
            url = f"{API_URL}/{id}"
            r = requests.patch(url, json=payload, timeout=timeout)
            return r.status_code, r.text
        except Exception as e:
            last = e
    raise last

# ───────────────────── DAG
default_args = {"owner": "geo", "retries": 1, "retry_delay": 60}

@dag(
    dag_id="ingest_geoassets",
    start_date=pendulum.datetime(2025, 8, 1, tz=TZ),
    schedule_interval=timedelta(seconds=100),  # ← 10초마다 검사
    catchup=False,
    default_args=default_args,
    max_active_runs=1,  # ← DAG 동시 실행 1개로 제한
    tags=["geo","ingest"]
)
def ingest_geoassets():
    @task
    def scan_and_process() -> List[Dict]:
        "인박스의 신규 파일만(업로드 완료분) 이동하고 API를 호출한다."
        if not INPUT_DIR.exists():
            raise FileNotFoundError(f"INPUT_DIR 없음: {INPUT_DIR}")

        files = sorted([p for p in INPUT_DIR.rglob('*') if p.is_file()])
        results: List[Dict] = []
        uploading_detected = False  # ← 이번 회차에 업로드 중 항목 존재 여부

        for p in files:
            name = p.name

            # SHP는 세트 전체 업로드 완료 여부 확인
            if p.suffix.lower() == ".shp":
                base = p.with_suffix("")
                required = [Path(f"{base}.dbf"), Path(f"{base}.shx")]
                if not all(x.exists() for x in required):
                    logging.info(f"SHP 세트 대기(필수 누락): {name}")
                    uploading_detected = True
                    continue
                shp_set = collect_shp_set(p)
                if any_locked(shp_set, 1.0):
                    logging.info(f"SHP 업로드 중 대기: {name}")
                    uploading_detected = True
                    continue
            # GeoJSON은 단일 파일이므로 업로드 중 여부만 확인
            if p.suffix.lower() == ".geojson":
                if is_locked(p, 1.0):
                    logging.info(f"업로드 중 대기: {name}")
                    uploading_detected = True
                    continue
            else:
                # TIFF 류 단일 파일만 비교
                if is_locked(p, 1.0):
                    logging.info(f"업로드 중 대기: {name}")
                    uploading_detected = True
                    continue

            # 분류 및 대상 폴더/소스 묶음
            meta = {}
            if (m := RE_TIFF.match(name)):
                meta = m.groupdict(); ym = meta["ym"]; atype="image"
                target_dir = PROJECT_ROOT / ym
                srcs = [p]
            elif (m := RE_SHP.match(name)):
                meta = m.groupdict(); ym = meta["ym"]; atype="digital"
                target_dir = PROJECT_ROOT / ym
                srcs = collect_shp_set(p)
            elif p.suffix.lower() in {".tif", ".tiff"}:
                ym = None; atype="image"; target_dir = PROJECT_ROOT / "unknown"; srcs=[p]
            elif p.suffix.lower() == ".shp":
                ym = None; atype="digital"; target_dir = PROJECT_ROOT / "unknown"; srcs=collect_shp_set(p)
            else:
                logging.info(f"무시: {name}")
                continue

            ts = pendulum.now(TZ).format("YYYYMMDDHHmmss")

            # 파일 이동
            moved = move_with_timestamp(srcs, target_dir, ts, atype)

            # API 호출을 위한 페이로드 준비
            first_name = moved[0].name
            if first_name.startswith("/app/"):
                first_name = first_name[len("/app/"):]
            if str(target_dir).startswith("/app/"):
                target_dir = Path(str(target_dir)[len("/app/"):])

            taken_start_at, taken_end_at = parse_ym_to_range(meta.get("ym")) if meta.get("ym") else (None, None)

            payload = {
                "file_name": first_name,
                "path": str(target_dir),
                "type": atype,
                "display_name": srcs[0].name if srcs else first_name,
                "platform": PLATFORM if atype == "image" else None,
                "full_path": str(target_dir),
                "taken_start_at": taken_start_at,
                "taken_end_at": taken_end_at,
            }
            if atype=="image" and "gsd" in meta:
                payload["gsd_cm"] = float(meta["gsd"])

            status, text = post_with_retry(payload)
            parsed = json.loads(text)
            resource_id = parsed["result"][0]["id"]
            results.append({
                "moved_files": [str(x) for x in moved],
                "payload": payload,
                "api_status": status,
                "api_response": text[:500],
                "resource_id": resource_id,
                "target_dir": str(target_dir),
                "atype": atype,
                "file_name" : moved[0].stem,
                "file_ext" : moved[0].suffix
            })

        # 이번 회차 업로드 진행 여부를 로그로 남김(필요 시 별도 메트릭/알람에 활용)
        if uploading_detected:
            logging.info("이번 회차에 업로드 중 파일이 있어 처리 보류된 항목이 있습니다(다음 크론에서 재확인).")

        return results


    @task
    def after_work(results: List[Dict[str, Any]]) -> None:
        # 리스트가 아니면 리스트로 감싸 통일
        items = results if isinstance(results, list) else [results]
        if not items:
            logging.info("신규 항목 없음.")
            return

        for r in items:
            td =  Path("/app") / Path(r["target_dir"])
            dest = td / f'{r["file_name"]}{r["file_ext"]}'
            atype = r.get("atype")

            if atype == "digital":
                subprocess.run(
                    [
                        "python3", "/opt/airflow/dags/utils/digital_map.py",
                        "--input_file", str(dest),
                        "--tif_output", str(dest.with_suffix(".tif")),
                        "--default_path", str(td),
                    ],
                    check=True,
                )
            elif atype == "image":
                try:
                    convert_to_cog_in_place(dest)
                except Exception:
                    logging.exception("COG 변환 실패")
                    raise

                gj = td / f'{r["file_name"]}_footprint.geojson'
                try:
                    
                    subprocess.run(
                        ["python3", "/opt/airflow/dags/utils/draw_footprint.py", str(dest), str(gj)],
                        check=True,
                        timeout=86400
                    )
                    if gj.exists():
                        payload = {
                            "foot_ptint_path": str(Path(r["target_dir"]) / f'{r["file_name"]}_footprint.geojson')
                        }
                        update_with_retry(payload, id=r["resource_id"])
                except Exception as e:
                    print(f"Failed to create footprint: {e}")   

            # 기존 키/동작 유지(오타 포함)


            logging.info("이동 완료: %s", r.get("moved_files"))
            logging.info("POST %s => %s", API_URL, r.get("api_status"))

    after_work(scan_and_process())

dag = ingest_geoassets()
