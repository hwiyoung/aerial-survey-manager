#!/bin/bash
# ============================================================
# OSM 타일 다운로드 스크립트
# 대한민국 영역의 오프라인 타일 다운로드
# ============================================================

set -e

TILES_DIR="${1:-./data/tiles}"
MIN_ZOOM="${2:-5}"
MAX_ZOOM="${3:-16}"

# 대한민국 바운딩 박스
MIN_LAT=33
MAX_LAT=39
MIN_LON=124
MAX_LON=132

echo "=============================================="
echo "OSM 타일 다운로드 스크립트"
echo "=============================================="
echo "저장 경로: $TILES_DIR"
echo "줌 레벨: $MIN_ZOOM - $MAX_ZOOM"
echo "영역: 대한민국 (${MIN_LAT}°N - ${MAX_LAT}°N, ${MIN_LON}°E - ${MAX_LON}°E)"
echo "=============================================="
echo ""

# 디렉토리 생성
mkdir -p "$TILES_DIR"

# Python 스크립트 실행
python3 << EOF
import os
import math
import urllib.request
import urllib.error
import time
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

TILES_DIR = "$TILES_DIR"
MIN_ZOOM = $MIN_ZOOM
MAX_ZOOM = $MAX_ZOOM
MIN_LAT = $MIN_LAT
MAX_LAT = $MAX_LAT
MIN_LON = $MIN_LON
MAX_LON = $MAX_LON

# 요청 헤더 (User-Agent 필수)
HEADERS = {
    'User-Agent': 'Aerial-Survey-Manager/1.0 (offline tile download)'
}

def lat_lon_to_tile(lat, lon, zoom):
    """위경도를 타일 좌표로 변환"""
    n = 2 ** zoom
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.log(math.tan(math.radians(lat)) + 1/math.cos(math.radians(lat))) / math.pi) / 2 * n)
    return x, y

def download_tile(z, x, y):
    """단일 타일 다운로드"""
    path = os.path.join(TILES_DIR, str(z), str(x), f"{y}.png")

    # 이미 존재하면 스킵
    if os.path.exists(path):
        return True, f"{z}/{x}/{y} (cached)"

    # URL 생성 (서버 로드 분산을 위해 서브도메인 사용)
    subdomain = ['a', 'b', 'c'][y % 3]
    url = f"https://{subdomain}.tile.openstreetmap.org/{z}/{x}/{y}.png"

    try:
        # 디렉토리 생성
        os.makedirs(os.path.dirname(path), exist_ok=True)

        # 다운로드
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=30) as response:
            with open(path, 'wb') as f:
                f.write(response.read())

        return True, f"{z}/{x}/{y}"
    except urllib.error.HTTPError as e:
        return False, f"{z}/{x}/{y} - HTTP {e.code}"
    except Exception as e:
        return False, f"{z}/{x}/{y} - {str(e)}"

def main():
    total_tiles = 0
    downloaded = 0
    failed = 0

    print("타일 수 계산 중...")

    # 각 줌 레벨별 타일 목록 생성
    all_tiles = []
    for z in range(MIN_ZOOM, MAX_ZOOM + 1):
        x1, y1 = lat_lon_to_tile(MAX_LAT, MIN_LON, z)
        x2, y2 = lat_lon_to_tile(MIN_LAT, MAX_LON, z)

        tiles = [(z, x, y) for x in range(x1, x2+1) for y in range(y1, y2+1)]
        all_tiles.extend(tiles)
        print(f"  줌 {z}: {len(tiles)}개 타일")

    total_tiles = len(all_tiles)
    print(f"\n총 {total_tiles}개 타일 다운로드 시작...")
    print("(OSM 정책 준수를 위해 요청 간 대기시간 적용)")
    print("")

    # 병렬 다운로드 (동시 요청 제한: 2개)
    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = {executor.submit(download_tile, z, x, y): (z, x, y) for z, x, y in all_tiles}

        for i, future in enumerate(as_completed(futures), 1):
            success, msg = future.result()
            if success:
                downloaded += 1
            else:
                failed += 1
                print(f"  실패: {msg}")

            # 진행률 표시 (100개마다)
            if i % 100 == 0 or i == total_tiles:
                pct = i / total_tiles * 100
                print(f"  진행: {i}/{total_tiles} ({pct:.1f}%) - 성공: {downloaded}, 실패: {failed}")

            # OSM 정책 준수: 요청 간 대기
            time.sleep(0.1)

    print("")
    print("============================================")
    print(f"다운로드 완료!")
    print(f"  성공: {downloaded}개")
    print(f"  실패: {failed}개")
    print(f"  저장 위치: {TILES_DIR}")
    print("============================================")

if __name__ == "__main__":
    main()
EOF

echo ""
echo "다운로드가 완료되었습니다."
echo ""
echo "사용 방법:"
echo "1. .env.production에 다음 설정 추가:"
echo "   VITE_MAP_OFFLINE=true"
echo "   VITE_TILE_URL=/tiles/{z}/{x}/{y}.png"
echo ""
echo "2. docker-compose.prod.yml에서 타일 볼륨 마운트:"
echo "   nginx:"
echo "     volumes:"
echo "       - ${TILES_DIR}:/data/tiles:ro"
echo ""
echo "3. nginx.prod.conf에 타일 서빙 설정 추가 (scripts/README-docker-compose-changes.md 참조)"
