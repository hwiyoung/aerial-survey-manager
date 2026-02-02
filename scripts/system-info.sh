#!/bin/bash
#
# Aerial Survey Manager - 시스템 정보 수집 스크립트
#

echo "=============================================="
echo "        System Information Report"
echo "=============================================="
echo ""

echo "[OS Information]"
echo "----------------"
cat /etc/os-release 2>/dev/null | grep -E "^(NAME|VERSION)=" || echo "Unknown OS"
echo "Kernel: $(uname -r)"
echo ""

echo "[Hardware]"
echo "----------"
echo "CPU: $(grep -m1 'model name' /proc/cpuinfo | cut -d: -f2 | xargs)"
echo "CPU Cores: $(nproc)"
echo "Memory: $(free -h | awk '/^Mem:/ {print $2}')"
echo ""

echo "[Disk Space]"
echo "------------"
df -h | grep -E "^/dev|Filesystem"
echo ""

echo "[Docker]"
echo "--------"
docker --version 2>/dev/null || echo "Docker not installed"
docker compose version 2>/dev/null || echo "Docker Compose not installed"
echo ""

echo "[NVIDIA GPU]"
echo "------------"
if command -v nvidia-smi &> /dev/null; then
    nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv,noheader 2>/dev/null || echo "GPU info unavailable"
else
    echo "NVIDIA driver not installed"
fi
echo ""

echo "[NVIDIA Container Toolkit]"
echo "--------------------------"
if docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo "Status: Working"
else
    echo "Status: Not working or not installed"
fi
echo ""

echo "[Network]"
echo "---------"
echo "Hostname: $(hostname)"
echo "IP Addresses:"
ip -4 addr show | grep -oP '(?<=inet\s)\d+(\.\d+){3}' | grep -v "127.0.0.1" | while read ip; do
    echo "  - $ip"
done
echo ""

echo "[Running Containers]"
echo "--------------------"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" 2>/dev/null || echo "No containers running"
echo ""

echo "=============================================="
echo "Report generated: $(date)"
echo "=============================================="
