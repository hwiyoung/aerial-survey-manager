#!/usr/bin/env bash
set -euo pipefail

if [ -z "${COMPOSE_FILE:-}" ]; then
    if [ -f docker-compose.prod.yml ]; then
        COMPOSE_FILE=docker-compose.prod.yml
    else
        COMPOSE_FILE=docker-compose.yml
    fi
fi
APPLY=false

usage() {
    cat <<'EOF'
Usage:
  ./scripts/migrate-orthomosaic-layout.sh [--apply] [--compose-file FILE]

Purpose:
  Convert each project's current COG from a legacy or v2.0.0-rc.1
  UUID-directory key to the flat orthomosaic/{region}_{title}.tif layout and
  update database paths in the same operation. If a filename is occupied, the
  first available name (1), (2), ... is selected automatically.

Default mode is dry-run. Active processing stops the command. Missing files,
invalid names, and extra RC files are reported and skipped.
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --apply)
            APPLY=true
            shift
            ;;
        -f|--compose-file)
            COMPOSE_FILE="${2:-}"
            if [ -z "$COMPOSE_FILE" ]; then
                echo "Missing compose file path" >&2
                exit 2
            fi
            shift 2
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown argument: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Compose file not found: $COMPOSE_FILE" >&2
    exit 2
fi

api_container=$(docker compose -f "$COMPOSE_FILE" ps -q api 2>/dev/null || true)
if [ -z "$api_container" ]; then
    echo "API service is not running for compose file: $COMPOSE_FILE" >&2
    exit 2
fi

script_path=$(docker compose -f "$COMPOSE_FILE" exec -T api sh -lc '
if [ -f /app/scripts/rename_orthomosaic_files.py ]; then
    echo /app/scripts/rename_orthomosaic_files.py
elif [ -f /app/scripts/rename_orthomosaic_files.pyc ]; then
    echo /app/scripts/rename_orthomosaic_files.pyc
else
    exit 2
fi
')

echo "compose_file=$COMPOSE_FILE"
echo "api_container=$api_container"
if [ "$APPLY" = true ]; then
    echo "mode=apply"
    docker compose -f "$COMPOSE_FILE" exec -T api python "$script_path" --apply
else
    echo "mode=dry-run"
    docker compose -f "$COMPOSE_FILE" exec -T api python "$script_path"
fi
