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

# 이미지 태깅 (버전 포함)
echo ""
echo "2. 이미지 태깅 중..."
docker tag ${IMAGE_PREFIX}-frontend:latest ${IMAGE_PREFIX}:frontend-${VERSION}
docker tag ${IMAGE_PREFIX}-api:latest ${IMAGE_PREFIX}:api-${VERSION}
docker tag ${IMAGE_PREFIX}-worker-metashape:latest ${IMAGE_PREFIX}:worker-metashape-${VERSION}
docker tag ${IMAGE_PREFIX}-celery-beat:latest ${IMAGE_PREFIX}:celery-beat-${VERSION}
docker tag ${IMAGE_PREFIX}-flower:latest ${IMAGE_PREFIX}:flower-${VERSION}

echo ""
echo "3. 배포용 docker-compose.yml 생성 중..."

# 배포용 docker-compose.yml 생성 (build 대신 image 사용)
cat > "$RELEASE_DIR/docker-compose.yml" << EOF
# ============================================================
# Aerial Survey Manager - 배포용 Docker Compose
# Version: ${VERSION}
# 주의: 이 파일은 빌드된 이미지를 사용합니다.
#       먼저 ./load-images.sh를 실행하세요.
# ============================================================

x-logging: &default-logging
  driver: "json-file"
  options:
    max-size: "10m"
    max-file: "3"

x-logging-worker: &worker-logging
  driver: "json-file"
  options:
    max-size: "50m"
    max-file: "5"

services:
  frontend:
    image: ${IMAGE_PREFIX}:frontend-${VERSION}
    pull_policy: never
    restart: always
    depends_on:
      - api
    networks:
      - aerial-network
    logging: *default-logging

  api:
    image: ${IMAGE_PREFIX}:api-${VERSION}
    pull_policy: never
    restart: always
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:\${POSTGRES_PASSWORD:-postgres}@db:5432/aerial_survey
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=\${MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_SECRET_KEY=\${MINIO_SECRET_KEY:-minioadmin}
      - MINIO_BUCKET=aerial-survey
      - JWT_SECRET_KEY=\${JWT_SECRET_KEY:-change-this-in-production}
      - EXTERNAL_ENGINE_URL=\${EXTERNAL_ENGINE_URL:-}
      - EXTERNAL_ENGINE_API_KEY=\${EXTERNAL_ENGINE_API_KEY:-}
      - MINIO_PUBLIC_ENDPOINT=\${MINIO_PUBLIC_ENDPOINT:-localhost:8081}
    volumes:
      - \${PROCESSING_DATA_PATH:-./data/processing}:/data/processing
      # 권역 GeoJSON 데이터 (초기 시드용)
      - ./data/regions:/app/data:ro
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_started
      minio:
        condition: service_started
    networks:
      - aerial-network
    logging: *default-logging

  worker-metashape:
    image: ${IMAGE_PREFIX}:worker-metashape-${VERSION}
    pull_policy: never
    restart: always
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: all
              capabilities: [gpu]
    environment:
      - PYTHONPATH=/app
      - DATABASE_URL=postgresql+asyncpg://postgres:\${POSTGRES_PASSWORD:-postgres}@db:5432/aerial_survey
      - REDIS_URL=redis://redis:6379/0
      - MINIO_ENDPOINT=minio:9000
      - MINIO_ACCESS_KEY=\${MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_SECRET_KEY=\${MINIO_SECRET_KEY:-minioadmin}
      - MINIO_BUCKET=aerial-survey
      - METASHAPE_LICENSE_KEY=\${METASHAPE_LICENSE_KEY:-}
      - PROJECT_ID=\${PROJECT_ID:-unknown}
      - PLATFORM_WEBHOOK_URL=http://api:8000/api/v1/processing/webhook
      - BACKEND_URL_ORTHO=http://api:8000/api/v1/processing
    volumes:
      - \${PROCESSING_DATA_PATH:-./data/processing}:/data/processing
      - metashape-license:/var/tmp/agisoft/licensing
    depends_on:
      - redis
      - db
      - minio
    networks:
      aerial-network:
        aliases:
          - worker-metashape
    mac_address: "02:42:AC:17:00:64"
    logging: *worker-logging

  celery-beat:
    image: ${IMAGE_PREFIX}:celery-beat-${VERSION}
    pull_policy: never
    command: celery -A app.workers.tasks beat --loglevel=info
    restart: always
    environment:
      - DATABASE_URL=postgresql+asyncpg://postgres:\${POSTGRES_PASSWORD:-postgres}@db:5432/aerial_survey
      - REDIS_URL=redis://redis:6379/0
      - MINIO_PUBLIC_ENDPOINT=\${MINIO_PUBLIC_ENDPOINT:-localhost:8081}
    depends_on:
      - redis
    networks:
      - aerial-network
    logging: *default-logging

  db:
    image: postgis/postgis:15-3.3
    restart: always
    environment:
      - POSTGRES_DB=aerial_survey
      - POSTGRES_USER=postgres
      - POSTGRES_PASSWORD=\${POSTGRES_PASSWORD:-postgres}
    volumes:
      - pgdata:/var/lib/postgresql/data
      - ./init.sql:/docker-entrypoint-initdb.d/init.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U postgres"]
      interval: 5s
      timeout: 5s
      retries: 5
    networks:
      - aerial-network
    logging: *default-logging

  redis:
    image: redis:7-alpine
    command: redis-server --appendonly yes
    restart: always
    volumes:
      - redis_data:/data
    networks:
      - aerial-network
    logging: *default-logging

  minio:
    image: minio/minio:latest
    command: server /data --console-address ":9001"
    restart: always
    environment:
      - MINIO_ROOT_USER=\${MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_ROOT_PASSWORD=\${MINIO_SECRET_KEY:-minioadmin}
      - MINIO_API_CORS_ALLOW_ORIGIN=*
    ports:
      - "127.0.0.1:9003:9001"
    volumes:
      - \${MINIO_DATA_PATH:-./data/minio}:/data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:9000/minio/health/live"]
      interval: 30s
      timeout: 20s
      retries: 3
    networks:
      - aerial-network
    logging: *default-logging

  minio-init:
    image: minio/mc
    depends_on:
      minio:
        condition: service_healthy
    entrypoint: ["/bin/sh", "-c"]
    command:
      - |
        mc alias set myminio http://minio:9000 \$\${MINIO_ACCESS_KEY:-minioadmin} \$\${MINIO_SECRET_KEY:-minioadmin}
        mc mb --ignore-existing myminio/aerial-survey
        mc anonymous set download myminio/aerial-survey/public
        echo "MinIO bucket initialized successfully"
    environment:
      - MINIO_ACCESS_KEY=\${MINIO_ACCESS_KEY:-minioadmin}
      - MINIO_SECRET_KEY=\${MINIO_SECRET_KEY:-minioadmin}
    networks:
      - aerial-network

  titiler:
    image: ghcr.io/developmentseed/titiler:0.18.0
    restart: always
    environment:
      - TITILER_API_CORS_ORIGINS=*
      - AWS_ACCESS_KEY_ID=\${MINIO_ACCESS_KEY:-minioadmin}
      - AWS_SECRET_ACCESS_KEY=\${MINIO_SECRET_KEY:-minioadmin}
      - AWS_S3_ENDPOINT=minio:9000
      - AWS_VIRTUAL_HOSTING=FALSE
      - AWS_HTTPS=NO
      - AWS_NO_SIGN_REQUEST=NO
    depends_on:
      - minio
    networks:
      - aerial-network
    logging: *default-logging

  nginx:
    image: nginx:alpine
    restart: always
    ports:
      - "80:80"                          # presigned URL용 (MinIO)
      - "\${WEB_PORT:-8081}:80"          # 웹 접속용
      - "\${HTTPS_PORT:-443}:443"        # HTTPS용
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/nginx/ssl:ro
    depends_on:
      - frontend
      - api
      - titiler
    networks:
      - aerial-network
    logging: *default-logging

  flower:
    image: ${IMAGE_PREFIX}:flower-${VERSION}
    pull_policy: never
    command: celery -A app.workers.tasks flower --port=5555
    restart: always
    environment:
      - REDIS_URL=redis://redis:6379/0
    ports:
      - "127.0.0.1:5555:5555"
    depends_on:
      - redis
    networks:
      - aerial-network
    logging: *default-logging

networks:
  aerial-network:
    driver: bridge
    ipam:
      config:
        - subnet: 172.23.0.0/16

volumes:
  pgdata:
  redis_data:
  metashape-license:
EOF

echo ""
echo "4. 기타 배포 파일 복사 중..."

# 필수 파일 복사
cp .env.production.example "$RELEASE_DIR/.env.example"
cp nginx.prod.conf "$RELEASE_DIR/nginx.conf"
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

# data 디렉토리 생성
mkdir -p "$RELEASE_DIR/data/processing"
mkdir -p "$RELEASE_DIR/data/minio"
mkdir -p "$RELEASE_DIR/data/regions"
touch "$RELEASE_DIR/data/processing/.gitkeep"
touch "$RELEASE_DIR/data/minio/.gitkeep"

# 권역 GeoJSON 데이터 복사 (초기 시드용)
echo "  - 권역 GeoJSON 데이터 복사 중..."
if [ -f "./data/전국_권역_5K_5179.geojson" ]; then
    cp "./data/전국_권역_5K_5179.geojson" "$RELEASE_DIR/data/regions/"
    echo "    ✓ 전국_권역_5K_5179.geojson 복사 완료"
else
    echo "    ⚠ 권역 GeoJSON 파일을 찾을 수 없습니다."
fi

echo ""
echo "5. Docker 이미지 저장 중..."

mkdir -p "$RELEASE_DIR/images"

# 커스텀 이미지 저장
echo "  - frontend 저장 중..."
docker save ${IMAGE_PREFIX}:frontend-${VERSION} | gzip > "$RELEASE_DIR/images/frontend.tar.gz"

echo "  - api 저장 중..."
docker save ${IMAGE_PREFIX}:api-${VERSION} | gzip > "$RELEASE_DIR/images/api.tar.gz"

echo "  - worker-metashape 저장 중..."
docker save ${IMAGE_PREFIX}:worker-metashape-${VERSION} | gzip > "$RELEASE_DIR/images/worker-metashape.tar.gz"

echo "  - celery-beat 저장 중..."
docker save ${IMAGE_PREFIX}:celery-beat-${VERSION} | gzip > "$RELEASE_DIR/images/celery-beat.tar.gz"

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
echo "6. 이미지 로드 스크립트 생성 중..."

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
echo "7. README 생성 중..."

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
echo "8. 패키지 압축 중..."

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
echo -e "${YELLOW}설치 순서:${NC}"
echo "  1. tar -xzf ${RELEASE_NAME}.tar.gz"
echo "  2. cd ${RELEASE_NAME}"
echo "  3. ./load-images.sh"
echo "  4. ./scripts/install.sh"
echo ""
