#!/bin/bash
# ============================================================
# Metashape Worker Entrypoint
# 컨테이너 종료 시 라이센스를 비활성화하지 않음 (오프라인 환경 지원)
# 라이센스 비활성화가 필요하면 수동으로 실행:
#   docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.py
# ============================================================

# 종료 신호 핸들러 — 자식 프로세스만 정리 (라이센스 유지)
cleanup() {
    echo ""
    echo "========================================"
    echo "[Entrypoint] SIGTERM/SIGINT 수신 - 종료 중..."
    echo "[Entrypoint] 라이센스는 유지됩니다 (수동 비활성화: docker exec ... deactivate.py)"
    echo "========================================"
    exit 0
}

# SIGTERM, SIGINT 신호 처리
trap cleanup SIGTERM SIGINT

echo "========================================"
echo "[Entrypoint] Metashape Worker 시작..."
echo "[Entrypoint] PID: $$"
echo "[Entrypoint] 명령어: $@"
echo "========================================"

# 라이센스 자동 활성화 (키가 있고 아직 활성화 안 된 경우)
if [ -n "$METASHAPE_LICENSE_KEY" ]; then
    python3 -c "
import Metashape
if Metashape.app.activated:
    print('[Entrypoint] 라이센스 이미 활성화됨')
else:
    import os
    key = os.environ.get('METASHAPE_LICENSE_KEY', '')
    try:
        Metashape.License().activate(key)
        print('[Entrypoint] 라이센스 활성화 완료')
    except Exception as e:
        print(f'[Entrypoint] 라이센스 활성화 실패: {e}')
        print('[Entrypoint] 오프라인 환경이면 인터넷 연결 후 재시작하세요')
" 2>&1
fi

# 원래 명령어 실행 (백그라운드)
exec "$@" &
CHILD_PID=$!

echo "[Entrypoint] 자식 프로세스 PID: $CHILD_PID"

# 자식 프로세스 대기
wait $CHILD_PID
EXIT_CODE=$?

echo "[Entrypoint] 자식 프로세스 종료 (exit code: $EXIT_CODE)"
exit $EXIT_CODE
