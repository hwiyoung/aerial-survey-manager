#!/bin/bash
# Backend API Entrypoint Script
# - 데이터베이스 마이그레이션 자동 실행
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

# API 서버 시작
echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
