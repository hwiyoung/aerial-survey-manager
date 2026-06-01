#!/usr/bin/env bash
# Start core services first, then try worker-engine as best effort.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$SCRIPT_DIR"

if [ -n "${COMPOSE_FILE:-}" ]; then
    COMPOSE_FILE_PATH="$COMPOSE_FILE"
elif [ -f docker-compose.prod.yml ]; then
    COMPOSE_FILE_PATH="docker-compose.prod.yml"
else
    COMPOSE_FILE_PATH="docker-compose.yml"
fi

echo "[aerial-systemd] compose_file=$COMPOSE_FILE_PATH"
docker compose -f "$COMPOSE_FILE_PATH" config >/dev/null

available_services="$(docker compose -f "$COMPOSE_FILE_PATH" config --services)"
has_service() {
    printf '%s\n' "$available_services" | grep -qx "$1"
}

core_services=()
for svc in db redis api frontend nginx celery-beat celery-worker celery-worker-thumbnail flower titiler; do
    if has_service "$svc"; then
        core_services+=("$svc")
    fi
done

if [ "${#core_services[@]}" -eq 0 ]; then
    echo "[aerial-systemd] ERROR: no core services found in $COMPOSE_FILE_PATH" >&2
    exit 1
fi

echo "[aerial-systemd] starting core services: ${core_services[*]}"
docker compose -f "$COMPOSE_FILE_PATH" up -d "${core_services[@]}"

if has_service worker-engine; then
    echo "[aerial-systemd] starting worker-engine as best effort"
    if ! docker compose -f "$COMPOSE_FILE_PATH" up -d --no-deps worker-engine; then
        echo "[aerial-systemd] WARN: worker-engine failed to start. Core services are up; aerial-gpu-watchdog.timer will retry recovery." >&2
    fi
fi

echo "[aerial-systemd] startup completed"
