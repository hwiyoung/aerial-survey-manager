#!/bin/bash
#
# Aerial Survey Manager - 헬스체크 스크립트
# 모든 서비스의 상태를 확인합니다.
#

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# 결과 카운터
PASS=0
FAIL=0
WARN=0

# 체크 함수
check_pass() {
    echo -e "  ${GREEN}✓${NC} $1"
    ((PASS++))
}

check_fail() {
    echo -e "  ${RED}✗${NC} $1"
    ((FAIL++))
}

check_warn() {
    echo -e "  ${YELLOW}!${NC} $1"
    ((WARN++))
}

# 스크립트 위치로 이동
cd "$(dirname "$0")/.."

echo ""
echo -e "${BLUE}=============================================="
echo "     Aerial Survey Manager Health Check"
echo "==============================================${NC}"
echo ""

# ============================================================
# Docker 서비스 상태 확인
# ============================================================
echo -e "${BLUE}[Docker Services]${NC}"

# compose 파일 확인
compose_file="docker-compose.yml"
if [ -f "docker-compose.prod.yml" ]; then
    compose_file="docker-compose.prod.yml"
fi

services=$(docker compose -f "$compose_file" ps --format json 2>/dev/null | jq -r '.Name' 2>/dev/null || docker compose -f "$compose_file" ps --services 2>/dev/null)

if [ -z "$services" ]; then
    check_fail "Docker 서비스가 실행되지 않았습니다"
else
    # 각 서비스 상태 확인
    for service in api frontend db redis minio nginx worker-metashape celery-beat titiler flower; do
        status=$(docker compose -f "$compose_file" ps "$service" --format "{{.Status}}" 2>/dev/null || echo "not found")
        if [[ "$status" == *"Up"* ]] || [[ "$status" == *"running"* ]]; then
            check_pass "$service: 실행 중"
        elif [[ "$status" == *"not found"* ]] || [[ -z "$status" ]]; then
            check_warn "$service: 서비스 없음"
        else
            check_fail "$service: $status"
        fi
    done
fi

echo ""

# ============================================================
# API 헬스체크
# ============================================================
echo -e "${BLUE}[API Health]${NC}"

api_health=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8081/health 2>/dev/null || echo "000")
if [ "$api_health" = "200" ]; then
    check_pass "API 서버: 정상 (HTTP $api_health)"
else
    check_fail "API 서버: 응답 없음 (HTTP $api_health)"
fi

echo ""

# ============================================================
# 데이터베이스 연결 확인
# ============================================================
echo -e "${BLUE}[Database]${NC}"

db_ready=$(docker compose -f "$compose_file" exec -T db pg_isready -U postgres 2>/dev/null || echo "failed")
if [[ "$db_ready" == *"accepting connections"* ]]; then
    check_pass "PostgreSQL: 연결 가능"
else
    check_fail "PostgreSQL: 연결 불가"
fi

echo ""

# ============================================================
# MinIO 스토리지 확인
# ============================================================
echo -e "${BLUE}[Storage]${NC}"

minio_health=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:9002/minio/health/live 2>/dev/null || echo "000")
if [ "$minio_health" = "200" ]; then
    check_pass "MinIO: 정상"
else
    check_fail "MinIO: 응답 없음"
fi

# 디스크 용량 확인
if [ -f ".env" ]; then
    minio_path=$(grep "^MINIO_DATA_PATH=" .env | cut -d'=' -f2)
    if [ -n "$minio_path" ] && [ -d "$minio_path" ]; then
        disk_usage=$(df -h "$minio_path" | awk 'NR==2 {print $5}' | sed 's/%//')
        disk_avail=$(df -h "$minio_path" | awk 'NR==2 {print $4}')
        if [ "$disk_usage" -gt 90 ]; then
            check_fail "MinIO 디스크: ${disk_usage}% 사용 중 (가용: $disk_avail) - 위험!"
        elif [ "$disk_usage" -gt 80 ]; then
            check_warn "MinIO 디스크: ${disk_usage}% 사용 중 (가용: $disk_avail)"
        else
            check_pass "MinIO 디스크: ${disk_usage}% 사용 중 (가용: $disk_avail)"
        fi
    fi
fi

echo ""

# ============================================================
# Redis 확인
# ============================================================
echo -e "${BLUE}[Redis]${NC}"

redis_ping=$(docker compose -f "$compose_file" exec -T redis redis-cli ping 2>/dev/null || echo "failed")
if [ "$redis_ping" = "PONG" ]; then
    check_pass "Redis: 정상"
else
    check_fail "Redis: 응답 없음"
fi

echo ""

# ============================================================
# GPU 확인
# ============================================================
echo -e "${BLUE}[GPU]${NC}"

if command -v nvidia-smi &> /dev/null; then
    gpu_info=$(nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader 2>/dev/null || echo "failed")
    if [ "$gpu_info" != "failed" ]; then
        check_pass "NVIDIA GPU: $gpu_info"
    else
        check_warn "GPU 정보를 가져올 수 없습니다"
    fi
else
    check_warn "NVIDIA 드라이버가 설치되어 있지 않습니다"
fi

# Worker에서 GPU 접근 확인
worker_gpu=$(docker compose -f "$compose_file" exec -T worker-metashape nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 || echo "failed")
if [ "$worker_gpu" != "failed" ] && [ -n "$worker_gpu" ]; then
    check_pass "Worker GPU 접근: $worker_gpu"
else
    check_warn "Worker에서 GPU 접근 불가"
fi

echo ""

# ============================================================
# Celery 워커 확인
# ============================================================
echo -e "${BLUE}[Celery Workers]${NC}"

celery_workers=$(docker compose -f "$compose_file" exec -T api celery -A app.workers.tasks inspect active --json 2>/dev/null || echo "{}")
if [[ "$celery_workers" == *"worker-metashape"* ]]; then
    check_pass "Metashape Worker: 활성"
else
    check_warn "Metashape Worker: 비활성 또는 연결 불가"
fi

echo ""

# ============================================================
# 결과 요약
# ============================================================
echo -e "${BLUE}=============================================="
echo "                   Summary"
echo "==============================================${NC}"
echo ""
echo -e "  ${GREEN}PASS${NC}: $PASS"
echo -e "  ${YELLOW}WARN${NC}: $WARN"
echo -e "  ${RED}FAIL${NC}: $FAIL"
echo ""

if [ $FAIL -gt 0 ]; then
    echo -e "${RED}일부 서비스에 문제가 있습니다. 로그를 확인하세요.${NC}"
    echo "  docker compose logs <service-name>"
    exit 1
elif [ $WARN -gt 0 ]; then
    echo -e "${YELLOW}경고 항목을 확인하세요.${NC}"
    exit 0
else
    echo -e "${GREEN}모든 서비스가 정상입니다.${NC}"
    exit 0
fi
