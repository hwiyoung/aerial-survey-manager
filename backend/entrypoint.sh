#!/bin/bash
# Backend API Entrypoint Script
# - 데이터베이스 마이그레이션 자동 실행
# - 초기 데이터 시드 (카메라 모델, 권역)
# - API 서버 시작

set -euo pipefail

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

# 다중 head는 배포 중 자동 병합하지 않고 빌드/개발 단계에서 명시적으로 해결한다.
HEAD_COUNT=$(alembic heads 2>/dev/null | wc -l)
if [ "$HEAD_COUNT" -gt 1 ]; then
    echo "Error: Multiple Alembic migration heads detected ($HEAD_COUNT)."
    echo "Resolve the migration graph before starting the service."
    alembic heads
    exit 1
fi

# 마이그레이션은 전부 성공해야만 서비스를 시작한다.
echo "  Applying migrations..."
alembic upgrade head
echo "  Migrations applied successfully."
echo "Migrations completed."

# 초기 데이터 시드 (최초 실행 시에만)
echo "Seeding initial data..."

# 카메라 모델 시드 (.pyc 우선, .py 폴백)
SEED_SCRIPT=""
if [ -f "scripts/seed_camera_models.pyc" ]; then
    SEED_SCRIPT="scripts/seed_camera_models.pyc"
elif [ -f "scripts/seed_camera_models.py" ]; then
    SEED_SCRIPT="scripts/seed_camera_models.py"
fi

if [ -n "$SEED_SCRIPT" ]; then
    echo "  - Syncing camera models from io.csv..."
    python "$SEED_SCRIPT" --sync 2>/dev/null || echo "    (camera model sync skipped; io.csv may be missing)"
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
    # SQL 덤프로 복원 (가장 확실한 방법)
    SEED_SQL=""
    for f in "scripts/regions_seed.sql" "/app/data/regions_seed.sql"; do
        if [ -f "$f" ]; then
            SEED_SQL="$f"
            break
        fi
    done

    if [ -n "$SEED_SQL" ]; then
        echo "  - Importing regions from SQL dump: $SEED_SQL..."
        python -c "
import asyncio, os

async def import_regions():
    from sqlalchemy.ext.asyncio import create_async_engine
    from sqlalchemy import text
    engine = create_async_engine(os.environ.get('DATABASE_URL'))
    with open('$SEED_SQL', 'r') as f:
        sql_content = f.read()
    # INSERT 문만 추출하여 실행
    statements = [line.strip() for line in sql_content.split('\n')
                  if line.strip().startswith('INSERT')]
    count = 0
    async with engine.begin() as conn:
        for stmt in statements:
            try:
                await conn.execute(text(stmt))
                count += 1
            except Exception:
                pass  # 중복 데이터 무시
    await engine.dispose()
    print(f'    Imported {count} region records')

asyncio.run(import_regions())
" 2>&1 || echo "    (regions SQL import failed)"
    else
        # SQL 없으면 GeoJSON 폴백
        REGION_FILE=""
        for f in \
            "/app/data/전국_권역_5K_5179.geojson" \
            "/app/data/TN_MAPINDX_5K_5179.geojson" \
            "/app/data/regions.geojson" \
            "data/전국_권역_5K_5179.geojson" \
            "data/TN_MAPINDX_5K_5179.geojson" \
            "data/regions.geojson"; do
            if [ -f "$f" ]; then
                REGION_FILE="$f"
                break
            fi
        done

        IMPORT_SCRIPT=""
        if [ -f "scripts/import_regions.pyc" ]; then
            IMPORT_SCRIPT="scripts/import_regions.pyc"
        elif [ -f "scripts/import_regions.py" ]; then
            IMPORT_SCRIPT="scripts/import_regions.py"
        fi

        if [ -n "$REGION_FILE" ] && [ -n "$IMPORT_SCRIPT" ]; then
            echo "  - Importing regions from $REGION_FILE..."
            python "$IMPORT_SCRIPT" "$REGION_FILE" 2>&1 || echo "    (regions import failed)"
        else
            echo "  - No regions data found, skipping..."
        fi
    fi
else
    echo "  - Regions already seeded ($REGION_COUNT records), skipping..."
fi

# 최초 공동 운영 계정 생성 (사용자가 없을 때만, ADMIN_* 배포 변수 사용)
echo "  - Checking initial operator account..."
ADMIN_BOOTSTRAP_SCRIPT=""
if [ -f "scripts/bootstrap_admin.pyc" ]; then
    ADMIN_BOOTSTRAP_SCRIPT="scripts/bootstrap_admin.pyc"
elif [ -f "scripts/bootstrap_admin.py" ]; then
    ADMIN_BOOTSTRAP_SCRIPT="scripts/bootstrap_admin.py"
fi

if [ -z "$ADMIN_BOOTSTRAP_SCRIPT" ]; then
    echo "Error: initial account bootstrap script not found"
    exit 1
fi

python "$ADMIN_BOOTSTRAP_SCRIPT"

echo "Initial data seeding completed."

# API 서버 시작
echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
