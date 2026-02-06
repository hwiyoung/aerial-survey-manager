#!/bin/bash
#
# .env 변경 후 컨테이너에 환경변수 반영
# 사용법: ./scripts/reload-env.sh [서비스명...]
#
# 예시:
#   ./scripts/reload-env.sh                  # 모든 앱 컨테이너 재생성
#   ./scripts/reload-env.sh worker-engine    # worker-engine만 재생성
#   ./scripts/reload-env.sh api worker-engine # api와 worker-engine 재생성
#

set -e

cd "$(dirname "$0")/.."

# 색상 정의
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 외부 이미지 서비스 (환경변수 변경이 거의 없는 서비스)
EXTERNAL_SERVICES="db redis minio minio-init titiler nginx"

# 앱 서비스 (환경변수 변경이 자주 있는 서비스)
APP_SERVICES="api frontend worker-engine celery-worker celery-beat flower"

if [ $# -eq 0 ]; then
    # 인자 없으면 모든 앱 서비스 재생성
    SERVICES="$APP_SERVICES"
    echo -e "${YELLOW}모든 앱 컨테이너에 .env 변경사항 반영 중...${NC}"
else
    # 특정 서비스만 재생성
    SERVICES="$@"
    echo -e "${YELLOW}지정된 컨테이너에 .env 변경사항 반영 중: $SERVICES${NC}"
fi

echo ""

# 컨테이너 재생성 (환경변수 반영)
docker compose up -d --force-recreate $SERVICES

echo ""
echo -e "${GREEN}✓ 환경변수가 반영되었습니다.${NC}"
echo ""

# 변경된 주요 환경변수 표시
echo "현재 적용된 주요 설정:"
echo "  - METASHAPE_LICENSE_KEY: $(docker exec aerial-worker-engine printenv METASHAPE_LICENSE_KEY 2>/dev/null | cut -c1-10)..."
echo "  - MINIO_PUBLIC_ENDPOINT: $(docker exec aerial-survey-manager-api-1 printenv MINIO_PUBLIC_ENDPOINT 2>/dev/null)"
echo ""
