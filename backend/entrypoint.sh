#!/bin/bash
# Backend API Entrypoint Script
# - 데이터베이스 마이그레이션 자동 실행
# - 초기 데이터 시드 (카메라 모델, 권역)
# - API 서버 시작

set -e

echo "=== Aerial Survey Manager API Starting ==="

# 데이터베이스 연결 대기
echo "Waiting for database..."
MAX_RETRIES=30
RETRY_COUNT=0
until python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import os

async def check_db():
    engine = create_async_engine(os.environ.get('DATABASE_URL'))
    async with engine.connect() as conn:
        await conn.execute(text('SELECT 1'))
    await engine.dispose()

asyncio.run(check_db())
" 2>/dev/null; do
    RETRY_COUNT=$((RETRY_COUNT + 1))
    if [ $RETRY_COUNT -ge $MAX_RETRIES ]; then
        echo "Error: Could not connect to database after $MAX_RETRIES attempts"
        exit 1
    fi
    echo "  Waiting for database... (attempt $RETRY_COUNT/$MAX_RETRIES)"
    sleep 2
done
echo "Database is ready."

# 마이그레이션 실행 (테이블 생성/업데이트)
echo "Running database migrations..."

# 다중 헤드 문제 확인 및 머지
HEAD_COUNT=$(alembic heads 2>/dev/null | wc -l)
if [ "$HEAD_COUNT" -gt 1 ]; then
    echo "  Multiple migration heads detected ($HEAD_COUNT), merging..."
    alembic merge heads -m "auto_merge_$(date +%Y%m%d%H%M%S)" 2>/dev/null || true
fi

# 마이그레이션 적용
alembic upgrade heads 2>/dev/null || {
    echo "  Migration via alembic failed, trying direct table creation..."
    # regions 테이블 직접 생성 (마이그레이션 실패 시 폴백)
    python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import os

async def ensure_tables():
    engine = create_async_engine(os.environ.get('DATABASE_URL'))
    async with engine.begin() as conn:
        # regions 테이블 존재 확인 및 생성
        result = await conn.execute(text(\"\"\"
            SELECT EXISTS (
                SELECT FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = 'regions'
            )
        \"\"\"))
        exists = result.scalar()

        if not exists:
            print('  Creating regions table directly...')
            await conn.execute(text(\"\"\"
                CREATE TABLE IF NOT EXISTS regions (
                    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                    name VARCHAR(100),
                    layer VARCHAR(100),
                    geom geometry(MULTIPOLYGON, 5179) NOT NULL
                )
            \"\"\"))
            await conn.execute(text(\"\"\"
                CREATE INDEX IF NOT EXISTS idx_regions_geom ON regions USING gist(geom)
            \"\"\"))
            print('  regions table created.')
        else:
            print('  regions table already exists.')
    await engine.dispose()

asyncio.run(ensure_tables())
" || echo "  Warning: Could not ensure tables, continuing..."
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
echo "  - Checking regions data..."
REGION_COUNT=$(python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
import os

async def count_regions():
    try:
        engine = create_async_engine(os.environ.get('DATABASE_URL'))
        async with engine.connect() as conn:
            result = await conn.execute(text('SELECT COUNT(*) FROM regions'))
            count = result.scalar()
            print(count)
        await engine.dispose()
    except:
        print(0)

asyncio.run(count_regions())
" 2>/dev/null || echo "0")

if [ "$REGION_COUNT" -eq 0 ] || [ -z "$REGION_COUNT" ]; then
    # GeoJSON 파일 경로 탐색 (다양한 이름 지원)
    REGION_FILE=""
    for f in "/app/data/전국_권역_5K_5179.geojson" "/app/data/regions.geojson" "data/전국_권역_5K_5179.geojson" "data/regions.geojson"; do
        if [ -f "$f" ]; then
            REGION_FILE="$f"
            break
        fi
    done

    if [ -n "$REGION_FILE" ] && [ -f "scripts/import_regions.py" ]; then
        echo "  - Importing regions from $REGION_FILE..."
        python scripts/import_regions.py "$REGION_FILE" 2>&1 || echo "    (regions import failed, will retry later)"
    else
        echo "  - No regions GeoJSON file found, skipping..."
        echo "    Searched paths: /app/data/*.geojson, data/*.geojson"
    fi
else
    echo "  - Regions already seeded ($REGION_COUNT records), skipping..."
fi

echo "Initial data seeding completed."

# API 서버 시작
echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
