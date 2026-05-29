#!/usr/bin/env bash
# Read-only GPU/kernel/Docker runtime diagnostics for deployment support.

set -u

section() {
    echo ""
    echo "== $1 =="
}

run_or_warn() {
    local label="$1"
    shift
    echo "\$ $*"
    if ! "$@"; then
        echo "WARN: $label failed"
    fi
}

find_packaged_worker_engine_image() {
    if [ -f docker-compose.yml ]; then
        docker compose config --images 2>/dev/null \
            | grep -E '^aerial-survey-manager:worker-engine-' \
            | head -n 1 && return 0
    fi

    docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
        | grep -E '^(aerial-survey-manager:worker-engine-|aerial-prod-worker-engine:latest$)' \
        | sort -r \
        | head -n 1
}

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR" || exit 1

kernel="$(uname -r 2>/dev/null || true)"

section "Kernel"
echo "uname -r: ${kernel:-unknown}"
uname -a 2>/dev/null || true

section "NVIDIA host driver"
if command -v nvidia-smi >/dev/null 2>&1; then
    run_or_warn "nvidia-smi" nvidia-smi
else
    echo "WARN: nvidia-smi not found"
fi

section "Docker NVIDIA runtime"
if command -v docker >/dev/null 2>&1; then
    docker info 2>/dev/null | grep -i nvidia || echo "WARN: docker info does not list nvidia runtime"
else
    echo "WARN: docker not found"
fi

section "Docker GPU container test"
if command -v docker >/dev/null 2>&1; then
    test_image="${GPU_TEST_IMAGE:-$(find_packaged_worker_engine_image || true)}"
    test_image="${test_image:-nvidia/cuda:12.0.0-base-ubuntu22.04}"
    echo "test_image=$test_image"
    run_or_warn "docker GPU runtime test" docker run --rm --gpus all --entrypoint nvidia-smi "$test_image" -L
else
    echo "WARN: docker not found"
fi

section "Kernel-matched NVIDIA module packages"
if command -v dpkg-query >/dev/null 2>&1 && [ -n "$kernel" ]; then
    matched="$(
        dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Abbrev}\n' 'linux-modules-nvidia-*' 2>/dev/null \
            | awk -v k="$kernel" '$3 ~ /^ii/ && index($1, k) {print}'
    )"
    if [ -n "$matched" ]; then
        printf '%s\n' "$matched"
    else
        echo "WARN: no installed linux-modules-nvidia-* package matches current kernel: $kernel"
        echo "Installed NVIDIA module packages:"
        dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Abbrev}\n' 'linux-modules-nvidia-*' 2>/dev/null \
            | awk '$3 ~ /^ii/ {print}' || true
    fi
else
    echo "WARN: dpkg-query unavailable or kernel unknown"
fi

section "Secure Boot"
if command -v mokutil >/dev/null 2>&1; then
    mokutil --sb-state 2>/dev/null || true
else
    echo "mokutil not found"
fi

section "systemd services"
if command -v systemctl >/dev/null 2>&1; then
    systemctl status aerial-survey.service --no-pager 2>/dev/null || true
    systemctl status aerial-gpu-watchdog.timer --no-pager 2>/dev/null || true
else
    echo "systemctl not found"
fi

section "systemd symlink check"
if command -v systemctl >/dev/null 2>&1; then
    systemctl cat aerial-survey.service 2>/dev/null | grep -E 'WorkingDirectory|EnvironmentFile|ExecStart' || true
fi

section "worker-engine container GPU"
if command -v docker >/dev/null 2>&1; then
    if [ -f docker-compose.prod.yml ]; then
        COMPOSE_ARGS=(-f docker-compose.prod.yml)
    elif [ -f docker-compose.yml ]; then
        COMPOSE_ARGS=(-f docker-compose.yml)
    else
        COMPOSE_ARGS=()
    fi

    worker_container=""
    if [ "${#COMPOSE_ARGS[@]}" -gt 0 ]; then
        worker_container="$(docker compose "${COMPOSE_ARGS[@]}" ps -q worker-engine 2>/dev/null || true)"
    fi

    if [ -n "$worker_container" ]; then
        docker exec "$worker_container" nvidia-smi -L 2>/dev/null || echo "WARN: worker-engine cannot run nvidia-smi"
    else
        echo "WARN: worker-engine container is not running"
    fi
fi
