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

# 마이그레이션 적용 (에러 발생 시 로그 출력)
echo "  Applying migrations..."
if alembic upgrade head; then
    echo "  Migrations applied successfully."
else
    echo "  WARNING: Migration encountered an error. Checking current state..."
    alembic current || true

    # 마이그레이션이 부분적으로 실패해도 계속 진행
    # (regions 테이블 충돌 등은 무시하고 다른 테이블은 생성됨)
    echo "  Attempting to continue despite migration error..."
fi
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
    echo "  - Seeding camera models..."
    python "$SEED_SCRIPT" 2>/dev/null || echo "    (camera models may already exist)"
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
        for f in "/app/data/전국_권역_5K_5179.geojson" "/app/data/regions.geojson" "data/전국_권역_5K_5179.geojson" "data/regions.geojson"; do
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

# 기본 관리자 계정 생성 (유저가 없을 때만)
echo "  - Checking admin account..."
python -c "
import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
import os

async def seed_admin():
    engine = create_async_engine(os.environ.get('DATABASE_URL'))
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as session:
        result = await session.execute(text('SELECT COUNT(*) FROM users'))
        count = result.scalar()
        if count == 0:
            from app.auth.jwt import hash_password
            pw = hash_password('siqms')
            # 기본 조직 생성
            await session.execute(text(
                \"INSERT INTO organizations (id, name, quota_storage_gb, quota_projects, created_at) \"
                \"VALUES (gen_random_uuid(), '기본 조직', 10000, 1000, now()) \"
                \"ON CONFLICT DO NOTHING\"
            ))
            org_result = await session.execute(text(\"SELECT id FROM organizations LIMIT 1\"))
            org_id = org_result.scalar()
            # 관리자 계정 생성 (조직 연결)
            await session.execute(text(
                \"INSERT INTO users (id, email, password_hash, name, role, is_active, organization_id, created_at) \"
                \"VALUES (gen_random_uuid(), 'admin', :pw, '관리자', 'admin', true, :org_id, now())\"
            ), {'pw': pw, 'org_id': org_id})
            await session.commit()
            print('    Default organization and admin account created (admin / siqms)')
        else:
            print(f'    Admin account already exists ({count} users), skipping...')
    await engine.dispose()

asyncio.run(seed_admin())
" 2>/dev/null || echo "    (admin seed skipped)"

echo "Initial data seeding completed."

# API 서버 시작
echo "Starting API server..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
