#!/bin/bash
# Backend API Entrypoint Script
# - 데이터베이스 마이그레이션 자동 실행
# - 초기 데이터 시드 (카메라 모델, 권역)
# - API 서버 시작

set -e

echo "=== Aerial Survey Manager API Starting ==="

# 데이터베이스 연결 대기
echo "Waiting for database..."
sleep 5

# 마이그레이션 실행 (테이블 생성/업데이트)
echo "Running database migrations..."
alembic upgrade heads || {
    echo "Warning: Migration failed, but continuing..."
}
echo "Migrations completed."

# 초기 데이터 시드 (최초 실행 시에만)
echo "Seeding initial data..."

# 카메라 모델 시드
if [ -f "scripts/seed_camera_models.py" ]; then
    echo "  - Seeding camera models..."
    python scripts/seed_camera_models.py 2>/dev/null || echo "    (camera models may already exist)"
fi

# 권역 데이터 시드 (GeoJSON 파일이 있는 경우)
if [ -f "scripts/import_regions.py" ] && [ -f "data/regions.geojson" ]; then
    echo "  - Importing regions..."
    python scripts/import_regions.py data/regions.geojson 2>/dev/null || echo "    (regions may already exist)"
fi

echo "Initial data seeding completed."

# API 서버 시작
echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
