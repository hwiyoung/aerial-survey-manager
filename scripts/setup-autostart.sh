#!/bin/bash
# ============================================================
# Aerial Survey Manager - 자동 시작 설정 스크립트
# 배포 PC 재부팅 시 Docker 및 컨테이너 자동 시작 설정
# ============================================================

set -e

echo "=== Docker 서비스 자동 시작 설정 ==="

# 1. Docker 서비스 활성화
echo "[1/4] Docker 서비스 시스템 시작 시 자동 실행 설정..."
sudo systemctl enable docker
sudo systemctl enable containerd

# 2. Docker 서비스 상태 확인
echo "[2/4] Docker 서비스 상태 확인..."
sudo systemctl status docker --no-pager || true

# 3. docker-compose.prod.yml의 restart 정책 확인
echo "[3/4] docker-compose.prod.yml restart 정책 확인..."
COMPOSE_FILE="${1:-./docker-compose.prod.yml}"
if [ -f "$COMPOSE_FILE" ]; then
    RESTART_COUNT=$(grep -c "restart: always" "$COMPOSE_FILE" 2>/dev/null || echo "0")
    if [ "$RESTART_COUNT" -gt 0 ]; then
        echo "  restart: always 설정 $RESTART_COUNT개 확인됨"
    else
        echo "  restart: always 설정이 없습니다. docker-compose.prod.yml을 확인하세요."
    fi
else
    echo "  $COMPOSE_FILE 파일을 찾을 수 없습니다."
fi

# 4. 현재 컨테이너 상태
echo "[4/4] 현재 컨테이너 상태..."
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null | head -20 || echo "Docker가 실행 중이 아닙니다."

echo ""
echo "=== 설정 완료 ==="
echo "시스템 재부팅 후 Docker와 모든 컨테이너가 자동으로 시작됩니다."
echo ""
echo "수동 재시작이 필요한 경우:"
echo "  cd $(pwd)"
echo "  docker compose -f docker-compose.prod.yml up -d"
echo ""
echo "Docker 자동 시작 확인:"
echo "  sudo systemctl is-enabled docker"
