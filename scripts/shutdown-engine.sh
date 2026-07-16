#!/bin/bash
# ============================================================
# 처리 엔진 안전 종료 스크립트
# docker-compose down 전에 처리 엔진 라이선스를 비활성화합니다.
# ============================================================

# Compose 파일 자동 감지 (개발환경: docker-compose.prod.yml 우선, 배포 패키지: docker-compose.yml)
if [ -n "$1" ]; then
    COMPOSE_FILE="$1"
elif [ -f "./docker-compose.prod.yml" ]; then
    COMPOSE_FILE="./docker-compose.prod.yml"
else
    COMPOSE_FILE="./docker-compose.yml"
fi
WORKER_SERVICE="worker-engine"

echo "=== 처리 엔진 안전 종료 프로세스 ==="
echo "Compose 파일: $COMPOSE_FILE"
echo ""

# Compose 파일 존재 확인
if [ ! -f "$COMPOSE_FILE" ]; then
    echo "오류: $COMPOSE_FILE 파일을 찾을 수 없습니다."
    echo "사용법: $0 [docker-compose 파일 경로]"
    exit 1
fi

# 1. 워커 상태 확인
echo "[1/4] 처리 엔진 워커 상태 확인..."
WORKER_STATUS=$(docker compose -f "$COMPOSE_FILE" ps -q "$WORKER_SERVICE" 2>/dev/null)
if [ -z "$WORKER_STATUS" ]; then
    echo "  워커가 실행 중이 아닙니다."
else
    echo "  워커가 실행 중입니다. (Container ID: $WORKER_STATUS)"
fi

# 2. 라이선스 비활성화
echo "[2/4] 처리 엔진 라이선스 비활성화 중..."
if [ -n "$WORKER_STATUS" ]; then
    docker compose -f "$COMPOSE_FILE" exec -T "$WORKER_SERVICE" sh -lc '
        deactivate_script="$(find /app/engines -path "*/pipeline/deactivate.pyc" -print -quit 2>/dev/null || true)"
        if [ -z "$deactivate_script" ]; then
            deactivate_script="$(find /app/engines -path "*/pipeline/deactivate.py" -print -quit 2>/dev/null || true)"
        fi
        if [ -n "$deactivate_script" ]; then
            python3 "$deactivate_script"
        else
            echo "  비활성화 스크립트를 찾을 수 없어 스킵합니다."
        fi
    ' 2>&1 || echo "  라이선스 비활성화 실패 (워커가 응답하지 않음)"
else
    echo "  워커가 실행 중이 아니므로 비활성화 스킵"
fi

# 3. 컨테이너 정상 종료 (SIGTERM)
echo "[3/4] 워커 컨테이너 종료 중..."
if [ -n "$WORKER_STATUS" ]; then
    docker compose -f "$COMPOSE_FILE" stop "$WORKER_SERVICE" --timeout 60
    echo "  워커 컨테이너가 종료되었습니다."
else
    echo "  이미 종료된 상태입니다."
fi

# 4. 전체 시스템 종료 (선택)
echo ""
read -p "[4/4] 전체 시스템을 종료하시겠습니까? (y/N): " confirm
if [[ "$confirm" =~ ^[Yy]$ ]]; then
    echo "전체 시스템 종료 중..."
    docker compose -f "$COMPOSE_FILE" down
    echo "전체 시스템이 종료되었습니다."
else
    echo "worker-engine만 종료되었습니다."
    echo "다른 서비스는 계속 실행 중입니다."
fi

echo ""
echo "=== 종료 완료 ==="
