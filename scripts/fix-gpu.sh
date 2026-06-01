#!/bin/bash
# GPU 진단 및 복구 스크립트
# 사용법: sudo bash fix-gpu.sh

set -e

echo "==============================="
echo " GPU 진단 시작"
echo "==============================="

# 1. 호스트 GPU 확인
echo ""
echo "[1/4] 호스트 GPU 확인..."
if nvidia-smi &>/dev/null; then
    echo "✅ 호스트 GPU 정상"
    nvidia-smi --query-gpu=name,driver_version --format=csv,noheader
else
    echo "❌ 호스트에서 GPU를 인식하지 못합니다."
    echo "   드라이버와 현재 커널 모듈 상태를 확인하세요."
    echo "   권장:"
    echo "     ubuntu-drivers devices"
    echo "     sudo ubuntu-drivers install"
    echo "     sudo reboot"
    exit 1
fi

# 2. NVIDIA Container Toolkit 확인
echo ""
echo "[2/4] NVIDIA Container Toolkit 확인..."
if dpkg -l | grep -q nvidia-container-toolkit; then
    echo "✅ NVIDIA Container Toolkit 설치됨"
else
    echo "⚠️  NVIDIA Container Toolkit 미설치 — 설치 진행합니다..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg 2>/dev/null
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        tee /etc/apt/sources.list.d/nvidia-container-toolkit.list > /dev/null
    apt-get update -qq
    apt-get install -y -qq nvidia-container-toolkit
    echo "✅ 설치 완료"

    echo ""
    echo "[2-1] Docker 데몬 재시작..."
    systemctl restart docker
    echo "✅ Docker 재시작 완료"
fi

# 3. Docker에서 GPU 전달 확인
echo ""
echo "[3/4] Docker 컨테이너 GPU 전달 확인..."
if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
    echo "✅ Docker GPU 전달 정상"
else
    echo "❌ Docker에서 GPU를 사용할 수 없습니다."
    echo "   Docker 데몬을 재시작합니다..."
    systemctl restart docker
    if docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null; then
        echo "✅ Docker 재시작 후 GPU 정상"
    else
        echo "❌ 여전히 GPU 사용 불가. 기술지원에 문의해주세요."
        exit 1
    fi
fi

# 4. worker-engine 재시작
echo ""
echo "[4/4] 처리 엔진 재시작..."
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"
if [ -f docker-compose.prod.yml ]; then
    COMPOSE_ARGS=(-f docker-compose.prod.yml)
elif [ -f docker-compose.yml ]; then
    COMPOSE_ARGS=(-f docker-compose.yml)
else
    echo "⚠️  docker-compose 파일을 찾지 못했습니다."
    exit 1
fi

docker compose "${COMPOSE_ARGS[@]}" up -d --force-recreate --no-deps worker-engine
echo "✅ worker-engine 재생성 완료"

# 5. 최종 확인
echo ""
echo "==============================="
echo " 최종 확인"
echo "==============================="
sleep 5
worker_container="$(docker compose "${COMPOSE_ARGS[@]}" ps -q worker-engine 2>/dev/null || true)"
if [ -n "$worker_container" ] && docker exec "$worker_container" nvidia-smi &>/dev/null; then
    echo "✅ worker-engine GPU 정상 작동"
    docker exec "$worker_container" nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
    echo ""
    echo "GPU가 정상 연결되었습니다."
    echo "현재 진행 중인 처리는 GPU 없이 진행되고 있으므로,"
    echo "처리를 중단하고 다시 시작하시면 GPU를 활용하여 빠르게 완료됩니다."
else
    echo "❌ worker-engine에서 여전히 GPU를 인식하지 못합니다."
    echo "   기술지원에 문의해주세요."
fi
