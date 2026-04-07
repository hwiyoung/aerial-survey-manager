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
    echo "   NVIDIA 드라이버 설치가 필요합니다."
    echo "   실행: sudo apt-get install -y nvidia-driver-535 && sudo reboot"
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
COMPOSE_DIR=$(find / -name "docker-compose.yml" -path "*/aerial-survey*" -not -path "*/engines/*" 2>/dev/null | head -1 | xargs dirname 2>/dev/null)
if [ -n "$COMPOSE_DIR" ]; then
    cd "$COMPOSE_DIR"
    docker compose restart worker-engine
    echo "✅ worker-engine 재시작 완료"
else
    echo "⚠️  docker-compose.yml 경로를 찾지 못했습니다."
    echo "   설치 경로에서 직접 실행해주세요: docker compose restart worker-engine"
fi

# 5. 최종 확인
echo ""
echo "==============================="
echo " 최종 확인"
echo "==============================="
sleep 5
if docker exec aerial-worker-engine nvidia-smi &>/dev/null; then
    echo "✅ worker-engine GPU 정상 작동"
    docker exec aerial-worker-engine nvidia-smi --query-gpu=name,memory.used,memory.total --format=csv,noheader
    echo ""
    echo "GPU가 정상 연결되었습니다."
    echo "현재 진행 중인 처리는 GPU 없이 진행되고 있으므로,"
    echo "처리를 중단하고 다시 시작하시면 GPU를 활용하여 빠르게 완료됩니다."
else
    echo "❌ worker-engine에서 여전히 GPU를 인식하지 못합니다."
    echo "   기술지원에 문의해주세요."
fi
