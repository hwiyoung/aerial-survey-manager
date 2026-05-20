#!/bin/bash
# Collect read-only evidence for host/container GPU runtime failures.

set -uo pipefail

REASON="manual"
DOCKER_SINCE="${GPU_DIAG_DOCKER_SINCE:-2h}"
JOURNAL_SINCE="${GPU_DIAG_JOURNAL_SINCE:-2 hours ago}"
OUTPUT_ROOT="${GPU_DIAG_ROOT:-}"
CONTAINER_NAME="${GPU_DIAG_CONTAINER:-aerial-worker-engine}"
COMPOSE_FILE_ARG="${COMPOSE_FILE:-}"
FALLBACK_OUTPUT_ROOT="/tmp/aerial-gpu-runtime-events"

usage() {
    cat << EOF
Usage: $0 [options]

Options:
  --reason TEXT          Reason label for this collection (default: manual)
  --since VALUE          Relative time for Docker logs/events (default: 2h)
  --journal-since VALUE  Relative time for journalctl (default: 2 hours ago)
  --output-root PATH     Output root directory
  --compose-file PATH    Compose file to inspect
  --container NAME       Worker container name (default: aerial-worker-engine)
  -h, --help             Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --reason)
            shift
            REASON="${1:-manual}"
            ;;
        --since)
            shift
            DOCKER_SINCE="${1:-2h}"
            ;;
        --journal-since)
            shift
            JOURNAL_SINCE="${1:-2 hours ago}"
            ;;
        --output-root)
            shift
            OUTPUT_ROOT="${1:-}"
            ;;
        --compose-file)
            shift
            COMPOSE_FILE_ARG="${1:-}"
            ;;
        --container)
            shift
            CONTAINER_NAME="${1:-aerial-worker-engine}"
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
    shift
done

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR" || exit 1

if [ -z "$OUTPUT_ROOT" ]; then
    OUTPUT_ROOT="$SCRIPT_DIR/diagnostics/gpu-runtime-events"
fi

if ! mkdir -p "$OUTPUT_ROOT" 2>/dev/null || [ ! -w "$OUTPUT_ROOT" ]; then
    echo "WARN: diagnostics output root is not writable: $OUTPUT_ROOT; falling back to $FALLBACK_OUTPUT_ROOT" >&2
    OUTPUT_ROOT="$FALLBACK_OUTPUT_ROOT"
    if ! mkdir -p "$OUTPUT_ROOT" 2>/dev/null || [ ! -w "$OUTPUT_ROOT" ]; then
        echo "ERROR: fallback diagnostics output root is not writable: $OUTPUT_ROOT" >&2
        exit 1
    fi
fi

if [ -n "$COMPOSE_FILE_ARG" ]; then
    COMPOSE_ARGS=(-f "$COMPOSE_FILE_ARG")
elif [ -f docker-compose.prod.yml ]; then
    COMPOSE_ARGS=(-f docker-compose.prod.yml)
else
    COMPOSE_ARGS=(-f docker-compose.yml)
fi

SAFE_REASON="$(printf '%s' "$REASON" | tr -cs 'A-Za-z0-9_.-' '-' | sed 's/^-//; s/-$//')"
if [ -z "$SAFE_REASON" ]; then
    SAFE_REASON="manual"
fi

STAMP="$(date '+%Y%m%d-%H%M%S')"
OUT_DIR="$OUTPUT_ROOT/${STAMP}-${SAFE_REASON}"
mkdir -p "$OUT_DIR"

run_capture() {
    local filename="$1"
    shift
    {
        echo "# started: $(date -Is)"
        echo "# cwd: $SCRIPT_DIR"
        echo "# command: $*"
        echo ""
        "$@"
        local status=$?
        echo ""
        echo "# exit_status: $status"
        echo "# finished: $(date -Is)"
    } > "$OUT_DIR/$filename" 2>&1
}

run_shell() {
    local filename="$1"
    shift
    local command="$*"
    {
        echo "# started: $(date -Is)"
        echo "# cwd: $SCRIPT_DIR"
        echo "# command: $command"
        echo ""
        bash -lc "$command"
        local status=$?
        echo ""
        echo "# exit_status: $status"
        echo "# finished: $(date -Is)"
    } > "$OUT_DIR/$filename" 2>&1
}

host_gpu_status="fail"
if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
    host_gpu_status="ok"
elif ! command -v nvidia-smi >/dev/null 2>&1; then
    host_gpu_status="missing-nvidia-smi"
fi

worker_container_id="$(docker ps -aqf "name=^/${CONTAINER_NAME}$" 2>/dev/null | head -1 || true)"
worker_state="$(docker inspect --format '{{.State.Status}}' "$CONTAINER_NAME" 2>/dev/null || echo "missing")"
worker_health="$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' "$CONTAINER_NAME" 2>/dev/null || echo "missing")"
worker_gpu_status="fail"
if [ "$worker_state" = "running" ] && docker exec "$CONTAINER_NAME" nvidia-smi -L >/dev/null 2>&1; then
    worker_gpu_status="ok"
elif [ "$worker_state" = "missing" ]; then
    worker_gpu_status="missing-container"
fi

device_requests="$(docker inspect --format '{{json .HostConfig.DeviceRequests}}' "$CONTAINER_NAME" 2>/dev/null || echo "null")"
compose_config_files="$(docker inspect --format '{{index .Config.Labels "com.docker.compose.project.config_files"}}' "$CONTAINER_NAME" 2>/dev/null || echo "unknown")"

cat > "$OUT_DIR/summary.txt" << EOF
reason=$REASON
created_at=$(date -Is)
repo=$SCRIPT_DIR
hostname=$(hostname 2>/dev/null || true)
user=$(id -un 2>/dev/null || true)
kernel=$(uname -r 2>/dev/null || true)
compose_file=${COMPOSE_ARGS[*]}
container=$CONTAINER_NAME
container_id=$worker_container_id
container_state=$worker_state
container_health=$worker_health
host_gpu_status=$host_gpu_status
worker_gpu_status=$worker_gpu_status
device_requests=$device_requests
compose_config_files=$compose_config_files
docker_since=$DOCKER_SINCE
journal_since=$JOURNAL_SINCE

This summary is an evidence snapshot, not a root-cause conclusion.
EOF

cat > "$OUT_DIR/manifest.txt" << EOF
GPU runtime diagnostics
=======================

Reason: $REASON
Created: $(date -Is)
Repository: $SCRIPT_DIR
Container: $CONTAINER_NAME
Docker since: $DOCKER_SINCE
Journal since: $JOURNAL_SINCE
Output: $OUT_DIR

Files in this directory are command outputs captured before or during watchdog recovery.
Failed commands are kept with their exit status.
EOF

run_capture "host-nvidia-smi.txt" nvidia-smi
run_capture "host-nvidia-smi-list.txt" nvidia-smi -L
run_capture "host-nvidia-smi-query.txt" nvidia-smi -q
run_shell "host-nvidia-driver.txt" "uname -a; echo; uname -r; echo; dkms status 2>/dev/null || true; echo; modinfo nvidia 2>/dev/null || true; echo; cat /proc/driver/nvidia/version 2>/dev/null || true; echo; lsmod | grep -E '^nvidia|^nvidia_uvm|^nvidia_drm|^nvidia_modeset' || true"
run_shell "host-journal-kernel-gpu.txt" "journalctl -k -b --since '$JOURNAL_SINCE' --no-pager 2>/dev/null | grep -Ei 'nvrm|nvidia|xid|gpu|uvm|nvml|pcie' | tail -500 || true"
run_shell "host-journal-power-runtime.txt" "journalctl --since '$JOURNAL_SINCE' --no-pager 2>/dev/null | grep -Ei 'suspend|hibernate|systemd-sleep|resume|docker|nvidia|nvrm|xid|nvml|gpu' | tail -800 || true"
run_shell "docker-journal.txt" "journalctl -u docker --since '$JOURNAL_SINCE' --no-pager 2>/dev/null | tail -800 || true"
run_shell "systemd-status.txt" "systemctl status docker aerial-survey aerial-gpu-watchdog.timer aerial-gpu-watchdog.service --no-pager 2>/dev/null || true"

run_capture "docker-info.txt" docker info
run_capture "docker-compose-ls.json" docker compose ls --format json
run_capture "docker-compose-ps.txt" docker compose "${COMPOSE_ARGS[@]}" ps
run_capture "docker-compose-config-worker-engine.txt" docker compose "${COMPOSE_ARGS[@]}" config worker-engine
run_capture "docker-inspect-worker-engine.json" docker inspect "$CONTAINER_NAME"
run_shell "docker-worker-state.txt" "docker inspect --format 'status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}} device_requests={{json .HostConfig.DeviceRequests}} restart_count={{.RestartCount}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' '$CONTAINER_NAME' 2>/dev/null || true"
run_shell "docker-events-worker-engine.txt" "docker events --since '$DOCKER_SINCE' --until '$(date -Is)' --filter container='$CONTAINER_NAME' 2>/dev/null || true"
run_capture "docker-logs-worker-engine.txt" docker logs --since "$DOCKER_SINCE" "$CONTAINER_NAME"

run_capture "worker-nvidia-smi.txt" docker exec "$CONTAINER_NAME" nvidia-smi
run_capture "worker-nvidia-smi-list.txt" docker exec "$CONTAINER_NAME" nvidia-smi -L
run_capture "worker-nvidia-smi-query.txt" docker exec "$CONTAINER_NAME" nvidia-smi -q
run_shell "worker-env.txt" "docker exec '$CONTAINER_NAME' sh -lc 'env | sort | grep -Ei \"^(NVIDIA|CUDA|METASHAPE|GPU|CELERY|HOSTNAME|PATH)=\" || true' 2>/dev/null || true"
run_shell "worker-processes.txt" "docker exec '$CONTAINER_NAME' sh -lc 'ps auxww | grep -Ei \"Metashape|metashape|process_project|celery\" | grep -v grep || true' 2>/dev/null || true"
run_shell "worker-healthcheck.txt" "docker inspect --format '{{json .State.Health}}' '$CONTAINER_NAME' 2>/dev/null || true"

echo "$OUT_DIR"
