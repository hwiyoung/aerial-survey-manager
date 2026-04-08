#!/bin/bash
#
# Aerial Survey Manager - 배포 패키지 빌드 스크립트
# 외부 기관 배포용 패키지를 생성합니다.
# 소스 코드 없이 Docker 이미지만 배포합니다.
#

set -e

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
NC='\033[0m'

# 스크립트 위치로 이동
cd "$(dirname "$0")/.."

VERSION=${1:-$(date +%Y%m%d)}
RELEASE_NAME="aerial-survey-manager-${VERSION}"
RELEASE_DIR="./releases/${RELEASE_NAME}"
IMAGE_PREFIX="aerial-survey-manager"
PROD_PROJECT="aerial-prod"  # 개발 이미지와 분리하기 위한 별도 프로젝트명

echo -e "${BLUE}=============================================="
echo "     Aerial Survey Manager Release Builder"
echo "==============================================${NC}"
echo ""
echo "Version: $VERSION"
echo "Output: ${RELEASE_DIR}.tar.gz"
echo ""

# 기존 릴리스 디렉토리 정리
rm -rf "$RELEASE_DIR"
mkdir -p "$RELEASE_DIR"

echo "1. 기존 배포 이미지 정리 중..."

# 배포용 이미지만 삭제 (개발용 aerial-survey-manager-*는 유지)
# - aerial-prod-* (프로덕션 빌드 이미지)
# - aerial-survey-manager:*-v* (버전 태그된 이미지)
PROD_IMAGES=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep "^${PROD_PROJECT}-" || true)
VERSIONED_IMAGES=$(docker images --format "{{.Repository}}:{{.Tag}}" | grep "^${IMAGE_PREFIX}:.*-v" || true)
ALL_RELEASE_IMAGES=$(echo -e "${PROD_IMAGES}\n${VERSIONED_IMAGES}" | grep -v "^$" | sort -u || true)

if [ -n "$ALL_RELEASE_IMAGES" ]; then
    echo "   배포 이미지 삭제:"
    echo "$ALL_RELEASE_IMAGES" | sed 's/^/     - /'
    echo "$ALL_RELEASE_IMAGES" | xargs docker rmi -f 2>/dev/null || true
    echo -e "   ${GREEN}✓ 삭제 완료${NC}"
else
    echo "   삭제할 배포 이미지 없음"
fi

echo -e "   ${BLUE}ℹ 개발용 이미지 (aerial-survey-manager-*)는 유지됨${NC}"

# 빌드 캐시 정리 (오래된 레이어 제거)
echo "   빌드 캐시 정리 중..."
docker builder prune -f > /dev/null 2>&1 || true

echo ""
echo "2. Docker 이미지 빌드 중 (캐시 없이)..."

# 프로덕션 이미지 빌드
# -p: 개발 이미지(aerial-survey-manager-*)와 분리된 프로젝트명 사용
# --no-cache: 항상 최신 코드 반영
docker compose -p ${PROD_PROJECT} -f docker-compose.prod.yml build --no-cache

# 이미지 태깅 (버전 포함)
# 소스: aerial-prod-* (프로덕션 빌드)
# 타겟: aerial-survey-manager:*-VERSION (배포 패키지용)
echo ""
echo "3. 이미지 태깅 중..."
docker tag ${PROD_PROJECT}-frontend:latest ${IMAGE_PREFIX}:frontend-${VERSION}
docker tag ${PROD_PROJECT}-api:latest ${IMAGE_PREFIX}:api-${VERSION}
docker tag ${PROD_PROJECT}-worker-engine:latest ${IMAGE_PREFIX}:worker-engine-${VERSION}
docker tag ${PROD_PROJECT}-celery-beat:latest ${IMAGE_PREFIX}:celery-beat-${VERSION}
docker tag ${PROD_PROJECT}-celery-worker:latest ${IMAGE_PREFIX}:celery-worker-${VERSION}
docker tag ${PROD_PROJECT}-flower:latest ${IMAGE_PREFIX}:flower-${VERSION}

echo ""
echo "4. 배포용 docker-compose.yml 생성 중..."

# docker-compose.prod.yml을 기반으로 build → image 변환
# 더 이상 heredoc으로 별도 관리하지 않음 — prod.yml이 유일한 소스
python3 << PYEOF
import re

with open('docker-compose.prod.yml', 'r') as f:
    content = f.read()

# 서비스별 이미지 매핑
VERSION = '${VERSION}'
PREFIX = '${IMAGE_PREFIX}'
service_images = {
    'frontend': f'{PREFIX}:frontend-{VERSION}',
    'api': f'{PREFIX}:api-{VERSION}',
    'worker-engine': f'{PREFIX}:worker-engine-{VERSION}',
    'celery-beat': f'{PREFIX}:celery-beat-{VERSION}',
    'celery-worker-thumbnail': f'{PREFIX}:celery-worker-{VERSION}',
    'celery-worker': f'{PREFIX}:celery-worker-{VERSION}',
    'flower': f'{PREFIX}:flower-{VERSION}',
}

lines = content.split('\n')
output = []
skip_build = False
build_indent = 0
current_service = None
i = 0

while i < len(lines):
    line = lines[i]
    stripped = line.strip()

    # 서비스 이름 감지 (2칸 들여쓰기)
    service_match = re.match(r'^  (\S[\w-]+):', line)
    if service_match and not line.startswith('    '):
        current_service = service_match.group(1)

    # build: 블록 시작 감지
    if stripped.startswith('build:') and current_service in service_images:
        indent = len(line) - len(line.lstrip())
        img = service_images[current_service]
        output.append(f'{" " * indent}image: {img}')
        output.append(f'{" " * indent}pull_policy: never')

        if stripped == 'build:':
            # 멀티라인 build 블록 — 하위 들여쓰기 전부 스킵
            i += 1
            while i < len(lines):
                next_stripped = lines[i].strip()
                next_indent = len(lines[i]) - len(lines[i].lstrip())
                if next_stripped == '' or next_indent > indent:
                    i += 1
                else:
                    break
            continue
        else:
            # 싱글라인 build: ./backend 등
            i += 1
            continue

    # 데이터 경로: ./data → ./data/regions (배포 패키지 구조에 맞게)
    if '- ./data:/app/data:ro' in line or '- ./data/regions:/app/data:ro' in line:
        indent = len(line) - len(line.lstrip())
        output.append(f'{" " * indent}- ./data/regions:/app/data:ro')
        i += 1
        continue

    output.append(line)
    i += 1

# 헤더 추가
header = f'# Aerial Survey Manager - 배포용 (v{VERSION})\n# 이 파일은 docker-compose.prod.yml에서 자동 생성됨\n'
result = header + '\n'.join(output)

with open('${RELEASE_DIR}/docker-compose.yml', 'w') as f:
    f.write(result)

print('  docker-compose.prod.yml → docker-compose.yml 변환 완료')
PYEOF

echo ""
echo "5. 기타 배포 파일 복사 중..."

# 필수 파일 복사
cp .env.production.example "$RELEASE_DIR/.env.example"
cp nginx.prod.conf "$RELEASE_DIR/nginx.prod.conf"
cp init.sql "$RELEASE_DIR/"

# scripts 디렉토리 복사
cp -r scripts "$RELEASE_DIR/"

# docs 복사
mkdir -p "$RELEASE_DIR/docs"
cp docs/DEPLOYMENT_GUIDE.md "$RELEASE_DIR/docs/"
cp docs/ADMIN_GUIDE.md "$RELEASE_DIR/docs/" 2>/dev/null || true

# SSL 자체 서명 인증서 자동 생성 (nginx 시작을 위해 필요)
echo ""
echo "4-1. SSL 인증서 생성 중..."
mkdir -p "$RELEASE_DIR/ssl"
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout "$RELEASE_DIR/ssl/key.pem" \
    -out "$RELEASE_DIR/ssl/cert.pem" \
    -subj "/CN=localhost/O=AerialSurvey/C=KR" 2>/dev/null
echo "  - 자체 서명 SSL 인증서가 생성되었습니다."
echo "  - 프로덕션 환경에서는 실제 인증서로 교체하세요."

# data/regions 디렉토리 생성 (시드 데이터용)
mkdir -p "$RELEASE_DIR/data/regions"

# 권역 GeoJSON 데이터 복사 (초기 시드용, 파일명 후보 순서대로 탐색)
echo "  - 권역 GeoJSON 데이터 복사 중..."
REGION_SRC=""
for candidate in \
    "./data/전국_권역_5K_5179.geojson" \
    "./data/TN_MAPINDX_5K_5179.geojson" \
    "./data/regions.geojson"; do
    if [ -f "$candidate" ]; then
        REGION_SRC="$candidate"
        break
    fi
done

if [ -n "$REGION_SRC" ]; then
    cp "$REGION_SRC" "$RELEASE_DIR/data/regions/regions.geojson"
    echo "    ✓ $(basename $REGION_SRC) → regions.geojson 복사 완료"
else
    echo "    ⚠ 권역 GeoJSON 파일을 찾을 수 없습니다. (data/*.geojson 없음)"
fi

# 카메라 모델 데이터 복사 (초기 시드용)
echo "  - 카메라 모델 데이터 복사 중..."
if [ -f "./data/io.csv" ]; then
    cp "./data/io.csv" "$RELEASE_DIR/data/regions/"
    echo "    ✓ io.csv 복사 완료"
else
    echo "    ⚠ io.csv 파일을 찾을 수 없습니다. data/io.csv 를 확인하세요."
fi

# 도엽(map sheet) GeoJSON 데이터 복사
echo "  - 도엽 GeoJSON 데이터 복사 중..."
SHEET_COUNT=0
for f in ./data/TN_MAPINDX_*K_5179.geojson; do
    if [ -f "$f" ]; then
        cp "$f" "$RELEASE_DIR/data/regions/"
        echo "    ✓ $(basename $f) 복사 완료"
        SHEET_COUNT=$((SHEET_COUNT + 1))
    fi
done
if [ "$SHEET_COUNT" -eq 0 ]; then
    echo "    ⚠ 도엽 GeoJSON 파일을 찾을 수 없습니다."
fi

# 처리 엔진 스크립트는 Docker 이미지 내부에 포함됨
# Python 버전 호환성 문제로 외부 마운트 제거됨
echo "  - 처리 엔진 스크립트: Docker 이미지 내부에 포함 (외부 마운트 없음)"

echo ""
echo "6. Docker 이미지 저장 중..."

mkdir -p "$RELEASE_DIR/images"

# 커스텀 이미지 저장
echo "  - frontend 저장 중..."
docker save ${IMAGE_PREFIX}:frontend-${VERSION} | gzip > "$RELEASE_DIR/images/frontend.tar.gz"

echo "  - api 저장 중..."
docker save ${IMAGE_PREFIX}:api-${VERSION} | gzip > "$RELEASE_DIR/images/api.tar.gz"

echo "  - worker-engine 저장 중..."
docker save ${IMAGE_PREFIX}:worker-engine-${VERSION} | gzip > "$RELEASE_DIR/images/worker-engine.tar.gz"

echo "  - celery-beat 저장 중..."
docker save ${IMAGE_PREFIX}:celery-beat-${VERSION} | gzip > "$RELEASE_DIR/images/celery-beat.tar.gz"

echo "  - celery-worker 저장 중..."
docker save ${IMAGE_PREFIX}:celery-worker-${VERSION} | gzip > "$RELEASE_DIR/images/celery-worker.tar.gz"

echo "  - flower 저장 중..."
docker save ${IMAGE_PREFIX}:flower-${VERSION} | gzip > "$RELEASE_DIR/images/flower.tar.gz"

# 외부 이미지 저장
echo "  - 외부 이미지 저장 중..."
docker pull postgis/postgis:15-3.3 2>/dev/null || true
docker pull redis:7-alpine 2>/dev/null || true
docker pull minio/minio:latest 2>/dev/null || true
docker pull minio/mc:latest 2>/dev/null || true
docker pull nginx:alpine 2>/dev/null || true
docker pull ghcr.io/developmentseed/titiler:0.18.0 2>/dev/null || true

docker save postgis/postgis:15-3.3 | gzip > "$RELEASE_DIR/images/postgis.tar.gz" 2>/dev/null || true
docker save redis:7-alpine | gzip > "$RELEASE_DIR/images/redis.tar.gz" 2>/dev/null || true
docker save minio/minio:latest | gzip > "$RELEASE_DIR/images/minio.tar.gz" 2>/dev/null || true
docker save minio/mc:latest | gzip > "$RELEASE_DIR/images/minio-mc.tar.gz" 2>/dev/null || true
docker save nginx:alpine | gzip > "$RELEASE_DIR/images/nginx.tar.gz" 2>/dev/null || true
docker save ghcr.io/developmentseed/titiler:0.18.0 | gzip > "$RELEASE_DIR/images/titiler.tar.gz" 2>/dev/null || true

echo ""
echo "7. 이미지 로드 스크립트 생성 중..."

cat > "$RELEASE_DIR/load-images.sh" << 'EOF'
#!/bin/bash
#
# Docker 이미지 로드 스크립트
#

cd "$(dirname "$0")"

echo "=============================================="
echo "     Docker 이미지 로드"
echo "=============================================="
echo ""

if [ ! -d "images" ]; then
    echo "ERROR: images 디렉토리를 찾을 수 없습니다."
    exit 1
fi

total=$(ls -1 images/*.tar.gz 2>/dev/null | wc -l)
current=0

for img in images/*.tar.gz; do
    if [ -f "$img" ]; then
        current=$((current + 1))
        echo "[$current/$total] Loading: $(basename $img)"
        if ! gunzip -c "$img" | docker load; then
            echo "ERROR: $img 로드 실패"
            exit 1
        fi
    fi
done

echo ""
echo "=============================================="
echo "     이미지 로드 완료!"
echo "=============================================="
echo ""
echo "다음 단계: ./scripts/install.sh"
EOF
chmod +x "$RELEASE_DIR/load-images.sh"

echo ""
echo "8. README 생성 중..."

cat > "$RELEASE_DIR/README.txt" << EOF
============================================================
Aerial Survey Manager - 정사영상 생성 플랫폼
Version: ${VERSION}
============================================================

설치 방법:
-----------
1. Docker 이미지 로드 (필수!):
   ./load-images.sh

2. 설치 스크립트 실행:
   ./scripts/install.sh

   또는 수동 설치:
   cp .env.example .env
   # .env 파일 편집
   docker compose up -d

3. 접속:
   http://your-server:8081

상세 가이드:
-----------
docs/DEPLOYMENT_GUIDE.md 참조

지원:
-----------
문제 발생 시 scripts/collect-logs.sh 실행 후 로그 파일 전달
EOF

echo ""
echo "9. 패키지 압축 중..."

cd releases
tar -czvf "${RELEASE_NAME}.tar.gz" "$RELEASE_NAME"
rm -rf "$RELEASE_NAME"

echo ""
echo "10. 로컬 .pyc 파일 정리 중..."
# 배포 빌드에서 생성된 .pyc 파일이 개발 환경에 영향을 주지 않도록 정리
cd ..
find engines/ -name "*.pyc" -delete 2>/dev/null || true
find engines/ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
find backend/ -name "*.pyc" -delete 2>/dev/null || true
find backend/ -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true
echo -e "   ${GREEN}✓ .pyc 파일 정리 완료${NC}"

echo ""
echo -e "${GREEN}=============================================="
echo "              빌드 완료!"
echo "==============================================${NC}"
echo ""
echo "배포 패키지: releases/${RELEASE_NAME}.tar.gz"
echo ""
echo -e "${YELLOW}설치 순서:${NC}"
echo "  1. tar -xzf ${RELEASE_NAME}.tar.gz"
echo "  2. cd ${RELEASE_NAME}"
echo "  3. ./load-images.sh"
echo "  4. ./scripts/install.sh"
echo ""
