#!/bin/bash
# Check GPU visibility and recreate worker-engine only when the GPU disappears.

set -uo pipefail

INTERVAL_SECONDS=120
RUN_ONCE=false
COLLECT_DIAGNOSTICS="${GPU_WATCHDOG_COLLECT_DIAGNOSTICS:-true}"
DIAG_SINCE="${GPU_WATCHDOG_DIAG_SINCE:-2h}"

while [ $# -gt 0 ]; do
    case "$1" in
        --once)
            RUN_ONCE=true
            ;;
        --interval)
            shift
            INTERVAL_SECONDS="${1:-120}"
            ;;
        *)
            echo "Usage: $0 [--once] [--interval seconds]"
            exit 2
            ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ -n "${COMPOSE_FILE:-}" ]; then
    COMPOSE_ARGS=(-f "$COMPOSE_FILE")
elif [ -f docker-compose.prod.yml ]; then
    COMPOSE_ARGS=(-f docker-compose.prod.yml)
else
    COMPOSE_ARGS=(-f docker-compose.yml)
fi

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

diagnostics_enabled() {
    case "$COLLECT_DIAGNOSTICS" in
        0|false|FALSE|no|NO|off|OFF)
            return 1
            ;;
        *)
            return 0
            ;;
    esac
}

collect_diagnostics() {
    local reason="$1"
    local diag_script="$SCRIPT_DIR/scripts/collect-gpu-runtime-diagnostics.sh"

    if ! diagnostics_enabled; then
        return 0
    fi

    if [ ! -x "$diag_script" ]; then
        log "WARN: GPU diagnostics collector is not executable: $diag_script"
        return 0
    fi

    log "Collecting GPU diagnostics: $reason"
    local output
    if output="$("$diag_script" --reason "$reason" --since "$DIAG_SINCE" --compose-file "${COMPOSE_ARGS[1]}" 2>&1)"; then
        log "GPU diagnostics saved: $output"
    else
        log "WARN: GPU diagnostics collection failed: $output"
    fi
}

worker_container_id() {
    docker compose "${COMPOSE_ARGS[@]}" ps -q worker-engine 2>/dev/null
}

worker_health_status() {
    local cid="$1"
    if [ -z "$cid" ]; then
        echo "missing"
        return 0
    fi

    docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$cid" 2>/dev/null || echo "missing"
}

worker_gpu_available() {
    local cid="$1"
    [ -n "$cid" ] && docker exec "$cid" nvidia-smi -L >/dev/null 2>&1
}

worker_has_active_task() {
    local cid="$1"
    local output
    local status

    if [ -z "$cid" ]; then
        return 1
    fi

    output="$(docker exec "$cid" sh -lc 'celery -A app.workers.tasks inspect active -d worker-engine@$HOSTNAME --timeout 20' 2>&1)"
    status=$?
    if [ "$status" -ne 0 ]; then
        log "WARN: Celery active task inspect failed. Treating worker as busy to avoid mid-job restart: $(printf '%s' "$output" | tr '\n' ' ' | cut -c1-180)"
        return 0
    fi
    if printf '%s\n' "$output" | grep -Eiq 'no nodes replied|error:'; then
        log "WARN: Celery active task inspect returned an uncertain response. Treating worker as busy: $(printf '%s' "$output" | tr '\n' ' ' | cut -c1-180)"
        return 0
    fi

    if printf '%s\n' "$output" | grep -Eq '(^|[[:space:]])-[[:space:]]empty[[:space:]]-'; then
        return 1
    fi

    printf '%s\n' "$output" | grep -Eq "^[[:space:]]*\\*|['\"]id['\"][[:space:]]*:"
}

worker_recovered() {
    local cid="$1"
    local health

    health="$(worker_health_status "$cid")"
    [ "$health" != "unhealthy" ] && worker_gpu_available "$cid"
}

ensure_worker_gpu() {
    if ! command -v nvidia-smi >/dev/null 2>&1; then
        log "WARN: nvidia-smi is not installed on host. Skipping worker recovery."
        collect_diagnostics "host-nvidia-smi-missing"
        return 2
    fi

    if ! nvidia-smi -L >/dev/null 2>&1; then
        log "WARN: host GPU is not available. Check NVIDIA driver/kernel state and reboot if the driver was updated."
        collect_diagnostics "host-gpu-unavailable"
        return 2
    fi

    local cid
    local health
    cid="$(worker_container_id)"
    health="$(worker_health_status "$cid")"

    if worker_recovered "$cid"; then
        log "worker-engine GPU visibility is OK."
        return 0
    fi

    if [ -z "$cid" ]; then
        log "worker-engine is not running. Recreating worker-engine."
    elif [ "$health" = "unhealthy" ]; then
        log "worker-engine health is unhealthy. Recovery candidate."
    else
        log "worker-engine cannot see GPU from inside the container. Recovery candidate."
    fi

    if worker_has_active_task "$cid"; then
        log "WARN: worker-engine has an active Celery task. Not restarting mid-job."
        collect_diagnostics "worker-recovery-needed-active-task"
        return 1
    fi

    log "worker-engine has no active Celery task. Recreating worker-engine with GPU device request."
    collect_diagnostics "worker-recovery-before-recreate"
    docker compose "${COMPOSE_ARGS[@]}" up -d --force-recreate --no-deps worker-engine
    sleep 15

    cid="$(worker_container_id)"
    health="$(worker_health_status "$cid")"
    if worker_recovered "$cid"; then
        log "worker-engine GPU visibility recovered. health=$health"
        return 0
    fi

    log "ERROR: worker-engine still failed recovery after recreate. health=$health"
    collect_diagnostics "worker-recovery-after-recreate-failed"
    return 1
}

while true; do
    ensure_worker_gpu || true
    if [ "$RUN_ONCE" = true ]; then
        exit 0
    fi
    sleep "$INTERVAL_SECONDS"
done
