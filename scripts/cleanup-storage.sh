#!/bin/bash
# cleanup-storage.sh - 기존 프로젝트의 불필요한 중복 파일을 정리합니다.
#
# 정리 대상:
#   1. MinIO: result.tif (result_cog.tif가 있는 프로젝트만)
#   2. 로컬: output/result_cog.tif (MinIO에 업로드 완료된 프로젝트만)
#
# 사용법:
#   ./scripts/cleanup-storage.sh              # 미리보기 (삭제하지 않음)
#   ./scripts/cleanup-storage.sh --execute    # 실제 삭제 수행
#
# 안전장치:
#   - 기본 모드는 dry-run (미리보기만, 삭제 안 함)
#   - MinIO result.tif는 result_cog.tif가 있을 때만 삭제
#   - 로컬 COG는 MinIO에 result_cog.tif가 있을 때만 삭제

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

WORKER_CONTAINER="aerial-worker-engine"
DRY_RUN=true

# ── Parse arguments ──────────────────────────────────────────────
while [ $# -gt 0 ]; do
    case "$1" in
        --execute)
            DRY_RUN=false
            shift
            ;;
        --help|-h)
            echo "사용법: $0 [--execute]"
            echo ""
            echo "  기본: 미리보기 모드 (삭제하지 않음)"
            echo "  --execute: 실제 삭제 수행"
            exit 0
            ;;
        *)
            echo -e "${RED}알 수 없는 옵션: $1${NC}"
            exit 1
            ;;
    esac
done

# ── Check container ──────────────────────────────────────────────
if ! docker inspect "$WORKER_CONTAINER" >/dev/null 2>&1; then
    echo -e "${RED}✗ ${WORKER_CONTAINER} 컨테이너가 실행 중이 아닙니다.${NC}"
    echo "  docker compose up -d worker-engine 으로 시작해주세요."
    exit 1
fi

CONTAINER_STATUS=$(docker inspect -f '{{.State.Status}}' "$WORKER_CONTAINER")
if [ "$CONTAINER_STATUS" != "running" ]; then
    echo -e "${RED}✗ ${WORKER_CONTAINER} 컨테이너 상태: ${CONTAINER_STATUS}${NC}"
    exit 1
fi

# ── Get processing data path ────────────────────────────────────
PROCESSING_HOST_PATH=$(docker inspect "$WORKER_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/data/processing"}}{{.Source}}{{end}}{{end}}')

if [ -z "$PROCESSING_HOST_PATH" ]; then
    echo -e "${YELLOW}⚠ /data/processing 마운트 경로를 찾을 수 없습니다. 로컬 정리는 건너뜁니다.${NC}"
    PROCESSING_HOST_PATH=""
fi

# ── Header ───────────────────────────────────────────────────────
echo ""
echo -e "${CYAN}========================================${NC}"
echo -e "${CYAN}  저장소 정리 스크립트${NC}"
if $DRY_RUN; then
    echo -e "${YELLOW}  모드: 미리보기 (삭제하지 않음)${NC}"
    echo -e "${YELLOW}  실제 삭제: --execute 옵션 사용${NC}"
else
    echo -e "${RED}  모드: 실제 삭제${NC}"
fi
echo -e "${CYAN}========================================${NC}"
echo ""

# ── Python script for MinIO cleanup ─────────────────────────────
PYTHON_CMD="
import sys
import os

DRY_RUN = ${DRY_RUN:+True}
if '${DRY_RUN}' == 'false':
    DRY_RUN = False
else:
    DRY_RUN = True

# Setup storage
from app.services.storage import StorageService
storage = StorageService()

# ── Phase 1: MinIO result.tif 정리 ──────────────────────────
print('=' * 60)
print('[1/2] MinIO 중복 result.tif 스캔 중...')
print('=' * 60)

# Find all ortho objects
all_ortho_objects = storage.list_objects(prefix='projects/', recursive=True)
ortho_by_project = {}
for obj_name in all_ortho_objects:
    # projects/{id}/ortho/result.tif or result_cog.tif
    parts = obj_name.split('/')
    if len(parts) >= 4 and parts[2] == 'ortho':
        project_id = parts[1]
        filename = parts[3]
        if project_id not in ortho_by_project:
            ortho_by_project[project_id] = set()
        ortho_by_project[project_id].add(filename)

minio_delete_count = 0
minio_freed_bytes = 0

for project_id, files in sorted(ortho_by_project.items()):
    if 'result.tif' in files and 'result_cog.tif' in files:
        key = f'projects/{project_id}/ortho/result.tif'
        try:
            size = storage.get_object_size(key)
        except Exception:
            size = 0
        size_mb = size / (1024 * 1024)
        minio_delete_count += 1
        minio_freed_bytes += size

        if DRY_RUN:
            print(f'  [삭제 예정] {key} ({size_mb:.1f} MB)')
        else:
            storage.delete_object(key)
            print(f'  [삭제 완료] {key} ({size_mb:.1f} MB)')

if minio_delete_count == 0:
    print('  정리할 MinIO result.tif가 없습니다.')
else:
    freed_gb = minio_freed_bytes / (1024 * 1024 * 1024)
    action = '삭제 예정' if DRY_RUN else '삭제 완료'
    print(f'')
    print(f'  MinIO result.tif: {minio_delete_count}개 {action} ({freed_gb:.2f} GB)')

# ── Phase 2: 로컬 COG 정리 ─────────────────────────────────
print('')
print('=' * 60)
print('[2/2] 로컬 COG 파일 스캔 중...')
print('=' * 60)

local_delete_count = 0
local_freed_bytes = 0
processing_base = '/data/processing'

if not os.path.isdir(processing_base):
    print(f'  처리 데이터 경로 없음: {processing_base}')
else:
    for project_id in sorted(os.listdir(processing_base)):
        project_dir = os.path.join(processing_base, project_id)
        if not os.path.isdir(project_dir):
            continue

        local_cog = os.path.join(project_dir, 'output', 'result_cog.tif')
        if not os.path.isfile(local_cog):
            continue

        # MinIO에 result_cog.tif가 있는지 확인
        minio_key = f'projects/{project_id}/ortho/result_cog.tif'
        if not storage.object_exists(minio_key):
            print(f'  [건너뜀] {local_cog} (MinIO에 COG 없음)')
            continue

        try:
            size = os.path.getsize(local_cog)
        except Exception:
            size = 0
        size_mb = size / (1024 * 1024)
        local_delete_count += 1
        local_freed_bytes += size

        if DRY_RUN:
            print(f'  [삭제 예정] {local_cog} ({size_mb:.1f} MB)')
        else:
            try:
                os.unlink(local_cog)
                # output 디렉토리가 비었으면 삭제
                output_dir = os.path.dirname(local_cog)
                if os.path.isdir(output_dir) and not os.listdir(output_dir):
                    os.rmdir(output_dir)
                print(f'  [삭제 완료] {local_cog} ({size_mb:.1f} MB)')
            except Exception as e:
                print(f'  [오류] {local_cog}: {e}')

if local_delete_count == 0:
    print('  정리할 로컬 COG 파일이 없습니다.')
else:
    freed_gb = local_freed_bytes / (1024 * 1024 * 1024)
    action = '삭제 예정' if DRY_RUN else '삭제 완료'
    print(f'')
    print(f'  로컬 COG: {local_delete_count}개 {action} ({freed_gb:.2f} GB)')

# ── Summary ─────────────────────────────────────────────────
print('')
print('=' * 60)
total_freed_gb = (minio_freed_bytes + local_freed_bytes) / (1024 * 1024 * 1024)
if DRY_RUN:
    print(f'[미리보기] 총 절약 가능: {total_freed_gb:.2f} GB')
    print(f'  - MinIO result.tif: {minio_delete_count}개 ({minio_freed_bytes / (1024**3):.2f} GB)')
    print(f'  - 로컬 COG: {local_delete_count}개 ({local_freed_bytes / (1024**3):.2f} GB)')
    if total_freed_gb > 0:
        print('')
        print('실제 삭제를 수행하려면 --execute 옵션을 사용하세요.')
else:
    print(f'[완료] 총 {total_freed_gb:.2f} GB 확보')
    print(f'  - MinIO result.tif: {minio_delete_count}개 삭제')
    print(f'  - 로컬 COG: {local_delete_count}개 삭제')
print('=' * 60)
"

# ── Execute ──────────────────────────────────────────────────────
docker exec "$WORKER_CONTAINER" python -c "$PYTHON_CMD"
EXIT_CODE=$?

echo ""
if [ $EXIT_CODE -eq 0 ]; then
    if $DRY_RUN; then
        echo -e "${GREEN}미리보기 완료. 실제 삭제: ./scripts/cleanup-storage.sh --execute${NC}"
    else
        echo -e "${GREEN}✅ 저장소 정리가 완료되었습니다.${NC}"
    fi
else
    echo -e "${RED}✗ 저장소 정리 중 오류가 발생했습니다.${NC}"
    exit 1
fi
