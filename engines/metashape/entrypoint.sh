#!/bin/bash
# ============================================================
# Metashape Worker Entrypoint
# SIGTERM 수신 시 라이센스 비활성화 후 종료
# ============================================================

# 종료 신호 핸들러
cleanup() {
    echo ""
    echo "========================================"
    echo "[Entrypoint] SIGTERM/SIGINT 수신 - Metashape 라이센스 비활성화 중..."
    echo "========================================"

    # 라이센스 비활성화 스크립트 실행 (.pyc 우선, .py 폴백)
    DEACTIVATE_SCRIPT=""
    if [ -f "/app/engines/metashape/dags/metashape/deactivate.pyc" ]; then
        DEACTIVATE_SCRIPT="/app/engines/metashape/dags/metashape/deactivate.pyc"
    elif [ -f "/app/engines/metashape/dags/metashape/deactivate.py" ]; then
        DEACTIVATE_SCRIPT="/app/engines/metashape/dags/metashape/deactivate.py"
    fi

    if [ -n "$DEACTIVATE_SCRIPT" ]; then
        python3 "$DEACTIVATE_SCRIPT"
        DEACTIVATE_RESULT=$?
        if [ $DEACTIVATE_RESULT -eq 0 ]; then
            echo "[Entrypoint] 라이센스 비활성화 완료"
        else
            echo "[Entrypoint] 라이센스 비활성화 실패 (exit code: $DEACTIVATE_RESULT)"
        fi
    else
        echo "[Entrypoint] deactivate 스크립트를 찾을 수 없습니다 (.pyc/.py)"
    fi

    echo "[Entrypoint] 종료합니다."
    exit 0
}

# SIGTERM, SIGINT 신호 처리
trap cleanup SIGTERM SIGINT

echo "========================================"
echo "[Entrypoint] Metashape Worker 시작..."
echo "[Entrypoint] PID: $$"
echo "[Entrypoint] 명령어: $@"
echo "========================================"

# 원래 명령어 실행 (백그라운드)
exec "$@" &
CHILD_PID=$!

echo "[Entrypoint] 자식 프로세스 PID: $CHILD_PID"

# 자식 프로세스 대기
wait $CHILD_PID
EXIT_CODE=$?

echo "[Entrypoint] 자식 프로세스 종료 (exit code: $EXIT_CODE)"
exit $EXIT_CODE
