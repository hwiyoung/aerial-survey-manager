#!/bin/bash
#
# Aerial Survey Manager - 배포 패키지 빌드 스크립트
# 외부 기관 배포용 패키지를 생성합니다.
#

set -e

# 색상 정의
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# 스크립트 위치로 이동
cd "$(dirname "$0")/.."

VERSION=${1:-$(date +%Y%m%d)}
RELEASE_NAME="aerial-survey-manager-${VERSION}"
RELEASE_DIR="./releases/${RELEASE_NAME}"

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

echo "1. Docker 이미지 빌드 중..."

# 프로덕션 이미지 빌드
docker compose -f docker-compose.prod.yml build

echo ""
echo "2. 배포 파일 복사 중..."

# 필수 파일 복사
cp docker-compose.prod.yml "$RELEASE_DIR/docker-compose.yml"
cp .env.production.example "$RELEASE_DIR/.env.example"
cp nginx.prod.conf "$RELEASE_DIR/nginx.conf"
cp init.sql "$RELEASE_DIR/"

# scripts 디렉토리 복사
cp -r scripts "$RELEASE_DIR/"

# docs 복사
mkdir -p "$RELEASE_DIR/docs"
cp docs/DEPLOYMENT_GUIDE.md "$RELEASE_DIR/docs/"
cp docs/ADMIN_GUIDE.md "$RELEASE_DIR/docs/" 2>/dev/null || true

# ssl 디렉토리 생성 (빈 디렉토리)
mkdir -p "$RELEASE_DIR/ssl"
touch "$RELEASE_DIR/ssl/.gitkeep"

# data 디렉토리 생성
mkdir -p "$RELEASE_DIR/data/processing"
mkdir -p "$RELEASE_DIR/data/minio"
touch "$RELEASE_DIR/data/processing/.gitkeep"
touch "$RELEASE_DIR/data/minio/.gitkeep"

echo ""
echo "3. Docker 이미지 저장 중... (시간이 소요됩니다)"

# 이미지 이름 목록
IMAGES=(
    "aerial-survey-manager-frontend"
    "aerial-survey-manager-api"
    "aerial-survey-manager-worker-metashape"
    "aerial-survey-manager-celery-beat"
    "aerial-survey-manager-flower"
)

# 이미지 저장
mkdir -p "$RELEASE_DIR/images"
for img in "${IMAGES[@]}"; do
    if docker images --format "{{.Repository}}" | grep -q "$img"; then
        echo "  - $img 저장 중..."
        docker save "$img:latest" | gzip > "$RELEASE_DIR/images/${img}.tar.gz"
    fi
done

# 외부 이미지 (선택적)
echo "  - 외부 이미지 저장 중..."
docker save postgis/postgis:15-3.3 | gzip > "$RELEASE_DIR/images/postgis.tar.gz" 2>/dev/null || true
docker save redis:7-alpine | gzip > "$RELEASE_DIR/images/redis.tar.gz" 2>/dev/null || true
docker save minio/minio:latest | gzip > "$RELEASE_DIR/images/minio.tar.gz" 2>/dev/null || true
docker save nginx:alpine | gzip > "$RELEASE_DIR/images/nginx.tar.gz" 2>/dev/null || true

echo ""
echo "4. 이미지 로드 스크립트 생성 중..."

cat > "$RELEASE_DIR/load-images.sh" << 'EOF'
#!/bin/bash
# Docker 이미지 로드 스크립트

set -e
cd "$(dirname "$0")"

echo "Docker 이미지를 로드합니다..."

for img in images/*.tar.gz; do
    if [ -f "$img" ]; then
        echo "Loading: $img"
        gunzip -c "$img" | docker load
    fi
done

echo "완료!"
EOF
chmod +x "$RELEASE_DIR/load-images.sh"

echo ""
echo "5. README 생성 중..."

cat > "$RELEASE_DIR/README.txt" << EOF
============================================================
Aerial Survey Manager - 정사영상 생성 플랫폼
Version: $VERSION
============================================================

설치 방법:
-----------
1. Docker 이미지 로드:
   ./load-images.sh

2. 환경 설정:
   cp .env.example .env
   # .env 파일을 편집하여 설정

3. 서비스 시작:
   docker compose up -d

4. 접속:
   http://your-server:8081

상세 가이드:
-----------
docs/DEPLOYMENT_GUIDE.md 참조

지원:
-----------
문제 발생 시 scripts/collect-logs.sh 실행 후 로그 파일 전달
EOF

echo ""
echo "6. 패키지 압축 중..."

cd releases
tar -czvf "${RELEASE_NAME}.tar.gz" "$RELEASE_NAME"
rm -rf "$RELEASE_NAME"

echo ""
echo -e "${GREEN}=============================================="
echo "              빌드 완료!"
echo "==============================================${NC}"
echo ""
echo "배포 패키지: releases/${RELEASE_NAME}.tar.gz"
echo ""
echo "이 파일을 외부 기관에 전달하세요."
