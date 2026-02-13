#!/bin/bash
# inject-cog.sh - 외부 COG/GeoTIFF를 프로젝트에 삽입하여 완료 상태로 만듭니다.
#
# 전제조건:
#   1. Docker 컨테이너 실행 중 (api, celery-worker, db)
#   2. 입력 파일이 유효한 GeoTIFF (CRS/투영 메타데이터 포함)
#   3. 프로젝트가 DB에 존재
#
# 사용법:
#   ./scripts/inject-cog.sh <project_id> <cog_file_path> [options]
#
# 옵션:
#   --gsd <value>   GSD (cm/pixel), 미지정 시 파일에서 자동 추출
#   --force         처리 중인 작업을 강제 취소하고 삽입
#
# 예시:
#   ./scripts/inject-cog.sh abc-def-123 /path/to/orthomosaic.tif
#   ./scripts/inject-cog.sh abc-def-123 /path/to/orthomosaic.tif --gsd 5.0
#   ./scripts/inject-cog.sh abc-def-123 /path/to/orthomosaic.tif --force

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Celery 태스크 트리거용 컨테이너 (API 컨테이너는 항상 실행 중)
TASK_CONTAINER="aerial-survey-manager-api-1"

# ── Parse arguments ──────────────────────────────────────────────
if [ $# -lt 2 ]; then
    echo -e "${RED}사용법: $0 <project_id> <cog_file_path> [--gsd <value>] [--force]${NC}"
    echo ""
    echo "옵션:"
    echo "  --gsd <value>   GSD (cm/pixel), 미지정 시 파일에서 자동 추출"
    echo "  --force         처리 중인 작업을 강제 취소하고 삽입"
    echo ""
    echo "예시:"
    echo "  $0 abc-def-123 /path/to/orthomosaic.tif"
    echo "  $0 abc-def-123 /path/to/orthomosaic.tif --gsd 5.0"
    echo "  $0 abc-def-123 /path/to/orthomosaic.tif --force"
    exit 1
fi

PROJECT_ID="$1"
COG_FILE="$2"
shift 2

GSD_CM=""
FORCE="False"

while [ $# -gt 0 ]; do
    case "$1" in
        --gsd)
            GSD_CM="$2"
            shift 2
            ;;
        --force)
            FORCE="True"
            shift
            ;;
        *)
            echo -e "${RED}알 수 없는 옵션: $1${NC}"
            exit 1
            ;;
    esac
done

# ── Validate inputs ─────────────────────────────────────────────
if [ ! -f "$COG_FILE" ]; then
    echo -e "${RED}✗ 파일을 찾을 수 없습니다: ${COG_FILE}${NC}"
    exit 1
fi

# Check file size
FILE_SIZE=$(stat -c%s "$COG_FILE" 2>/dev/null || stat -f%z "$COG_FILE" 2>/dev/null)
FILE_SIZE_MB=$((FILE_SIZE / 1024 / 1024))
echo -e "${BLUE}📄 입력 파일: ${COG_FILE} (${FILE_SIZE_MB} MB)${NC}"

# Check container is running
if ! docker inspect "$TASK_CONTAINER" >/dev/null 2>&1; then
    echo -e "${RED}✗ ${TASK_CONTAINER} 컨테이너가 실행 중이 아닙니다.${NC}"
    echo -e "  docker compose up -d 으로 시작해주세요."
    exit 1
fi

CONTAINER_STATUS=$(docker inspect -f '{{.State.Status}}' "$TASK_CONTAINER")
if [ "$CONTAINER_STATUS" != "running" ]; then
    echo -e "${RED}✗ ${TASK_CONTAINER} 컨테이너 상태: ${CONTAINER_STATUS}${NC}"
    exit 1
fi

# ── Get processing data path ────────────────────────────────────
# Find the host path mounted to /data/processing in the worker container
PROCESSING_HOST_PATH=$(docker inspect "$TASK_CONTAINER" \
    --format '{{range .Mounts}}{{if eq .Destination "/data/processing"}}{{.Source}}{{end}}{{end}}')

if [ -z "$PROCESSING_HOST_PATH" ]; then
    echo -e "${RED}✗ /data/processing 마운트 경로를 찾을 수 없습니다.${NC}"
    exit 1
fi

echo -e "${BLUE}📁 처리 데이터 경로: ${PROCESSING_HOST_PATH}${NC}"

# ── Copy file to output directory ──────────────────────────────
OUTPUT_DIR="${PROCESSING_HOST_PATH}/${PROJECT_ID}/output"
DEST_FILE="${OUTPUT_DIR}/result_cog.tif"

echo -e "${BLUE}📋 출력 디렉토리로 복사 중...${NC}"
mkdir -p "$OUTPUT_DIR"
cp "$COG_FILE" "$DEST_FILE"
echo -e "${GREEN}✓ 복사 완료: ${DEST_FILE}${NC}"

# ── Build Python command ────────────────────────────────────────
GSD_ARG="None"
if [ -n "$GSD_CM" ]; then
    GSD_ARG="$GSD_CM"
fi

PYTHON_CMD="
from app.workers.tasks import inject_external_cog
from celery.exceptions import TimeoutError
import sys

print('Celery 태스크 전송 중...')
result = inject_external_cog.delay(
    '${PROJECT_ID}',
    '/data/processing/${PROJECT_ID}/output/result_cog.tif',
    gsd_cm=${GSD_ARG},
    force=${FORCE}
)
task_id = result.id
print(f'태스크 ID: {task_id}')
print('결과 대기 중... (최대 10분)')

try:
    res = result.get(timeout=600)
    if res.get('status') == 'completed':
        print()
        print('=' * 50)
        print(f'  프로젝트: ${PROJECT_ID}')
        print(f'  GSD: {res.get(\"gsd_cm\", \"N/A\")} cm/pixel')
        print(f'  Size: {res.get(\"size\", 0) / (1024*1024):.1f} MB')
        print(f'  MinIO: {res.get(\"result_path\", \"\")}')
        print('=' * 50)
        print('완료!')
    else:
        print(f'오류: {res.get(\"message\", \"알 수 없는 오류\")}')
        sys.exit(1)
except TimeoutError:
    print()
    print('=' * 50)
    print(f'  대기 시간(10분)을 초과했지만 태스크는 백그라운드에서 계속 실행 중입니다.')
    print(f'  태스크 ID: {task_id}')
    print()
    print(f'  진행 상황 확인:')
    print(f'    docker logs aerial-survey-manager-celery-worker-1 --tail=20')
    print('=' * 50)
    sys.exit(2)
except Exception as e:
    print(f'태스크 실행 실패: {e}')
    sys.exit(1)
"

# ── Execute Celery task ─────────────────────────────────────────
echo -e "${BLUE}🚀 COG 삽입 태스크 실행 중...${NC}"
echo ""

docker exec "$TASK_CONTAINER" python3 -c "$PYTHON_CMD"
EXIT_CODE=$?

if [ $EXIT_CODE -eq 0 ]; then
    echo ""
    echo -e "${GREEN}✅ COG 삽입이 완료되었습니다.${NC}"
    echo -e "${YELLOW}   웹에서 프로젝트를 확인해주세요.${NC}"
elif [ $EXIT_CODE -eq 2 ]; then
    echo ""
    echo -e "${YELLOW}⏳ 태스크가 백그라운드에서 실행 중입니다.${NC}"
    echo -e "${YELLOW}   완료 후 웹에서 프로젝트를 확인해주세요.${NC}"
else
    echo ""
    echo -e "${RED}✗ COG 삽입에 실패했습니다.${NC}"
    exit 1
fi
