#!/bin/bash
#
# Aerial Survey Manager - 로그 수집 스크립트
# 문제 해결을 위한 로그를 수집합니다.
#

set -e

# 스크립트 위치로 이동
cd "$(dirname "$0")/.."

# 출력 디렉토리
OUTPUT_DIR="./logs_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$OUTPUT_DIR"

echo "로그 수집을 시작합니다..."
echo "출력 디렉토리: $OUTPUT_DIR"
echo ""

# compose 파일 확인
compose_file="docker-compose.yml"
if [ -f "docker-compose.prod.yml" ]; then
    compose_file="docker-compose.prod.yml"
fi

# Docker 서비스 상태
echo "1. Docker 서비스 상태 수집..."
docker compose -f "$compose_file" ps > "$OUTPUT_DIR/docker-ps.txt" 2>&1 || true

# 각 서비스 로그 수집
services="api frontend db redis minio nginx worker-metashape celery-beat titiler flower"

for service in $services; do
    echo "2. $service 로그 수집..."
    docker compose -f "$compose_file" logs --tail=1000 "$service" > "$OUTPUT_DIR/${service}.log" 2>&1 || true
done

# 환경 설정 (비밀번호 제외)
echo "3. 환경 설정 수집..."
if [ -f ".env" ]; then
    grep -v -E "(PASSWORD|SECRET|KEY)" .env > "$OUTPUT_DIR/env-sanitized.txt" 2>/dev/null || true
fi

# 디스크 용량
echo "4. 디스크 정보 수집..."
df -h > "$OUTPUT_DIR/disk-usage.txt" 2>&1 || true

# 메모리 사용량
echo "5. 메모리 정보 수집..."
free -h > "$OUTPUT_DIR/memory.txt" 2>&1 || true

# Docker 리소스 사용량
echo "6. Docker 리소스 사용량 수집..."
docker stats --no-stream > "$OUTPUT_DIR/docker-stats.txt" 2>&1 || true

# GPU 정보
echo "7. GPU 정보 수집..."
nvidia-smi > "$OUTPUT_DIR/gpu-info.txt" 2>&1 || echo "GPU 정보 없음" > "$OUTPUT_DIR/gpu-info.txt"

# 압축
echo ""
echo "로그 파일 압축 중..."
tar -czf "${OUTPUT_DIR}.tar.gz" "$OUTPUT_DIR"
rm -rf "$OUTPUT_DIR"

echo ""
echo "완료! 로그 파일: ${OUTPUT_DIR}.tar.gz"
echo "이 파일을 지원팀에 전달해주세요."
