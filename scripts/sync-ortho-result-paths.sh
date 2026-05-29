#!/usr/bin/env bash
set -euo pipefail

COMPOSE_FILE=${COMPOSE_FILE:-docker-compose.yml}
DB_SERVICE=${DB_SERVICE:-db}
APPLY=false

usage() {
    cat <<'EOF'
Usage:
  ./scripts/sync-ortho-result-paths.sh [--apply] [--compose-file FILE]

Purpose:
  Sync the latest processing_jobs.result_path for each project to projects.ortho_path.

Default mode is dry-run. Use --apply to update the database.
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

db_container=$(docker compose -f "$COMPOSE_FILE" ps -q "$DB_SERVICE" 2>/dev/null || true)
if [ -z "$db_container" ]; then
    echo "Database service is not available in compose file: $DB_SERVICE" >&2
    exit 2
fi

echo "compose_file=$COMPOSE_FILE"
echo "db_service=$DB_SERVICE"
if [ "$APPLY" = true ]; then
    echo "mode=apply"
else
    echo "mode=dry-run"
fi
echo

if [ "$APPLY" = true ]; then
    docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" sh -lc '
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-aerial_survey}" -P pager=off
' <<'SQL'
\pset null '<NULL>'
WITH latest_jobs AS (
    SELECT DISTINCT ON (project_id)
        id,
        project_id,
        status,
        result_path,
        started_at,
        completed_at
    FROM processing_jobs
    ORDER BY project_id, started_at DESC NULLS LAST, completed_at DESC NULLS LAST
),
to_update AS (
    SELECT
        p.id AS project_id,
        p.title AS project_title,
        l.id AS job_id,
        l.status AS job_status,
        l.result_path AS before_path,
        p.ortho_path AS after_path
    FROM projects p
    JOIN latest_jobs l ON l.project_id = p.id
    WHERE NULLIF(p.ortho_path, '') IS NOT NULL
      AND l.result_path IS DISTINCT FROM p.ortho_path
),
updated AS (
    UPDATE processing_jobs j
    SET result_path = u.after_path
    FROM to_update u
    WHERE j.id = u.job_id
    RETURNING
        u.project_id,
        u.project_title,
        u.job_id,
        u.job_status,
        u.before_path,
        u.after_path
)
SELECT
    project_id,
    project_title,
    job_id,
    job_status,
    before_path,
    after_path
FROM updated
ORDER BY project_id;
SQL
else
    docker compose -f "$COMPOSE_FILE" exec -T "$DB_SERVICE" sh -lc '
psql -v ON_ERROR_STOP=1 -U "${POSTGRES_USER:-postgres}" -d "${POSTGRES_DB:-aerial_survey}" -P pager=off
' <<'SQL'
\pset null '<NULL>'
WITH latest_jobs AS (
    SELECT DISTINCT ON (project_id)
        id,
        project_id,
        status,
        result_path,
        started_at,
        completed_at
    FROM processing_jobs
    ORDER BY project_id, started_at DESC NULLS LAST, completed_at DESC NULLS LAST
),
to_update AS (
    SELECT
        p.id AS project_id,
        p.title AS project_title,
        l.id AS job_id,
        l.status AS job_status,
        l.result_path AS before_path,
        p.ortho_path AS after_path
    FROM projects p
    JOIN latest_jobs l ON l.project_id = p.id
    WHERE NULLIF(p.ortho_path, '') IS NOT NULL
      AND l.result_path IS DISTINCT FROM p.ortho_path
)
SELECT
    project_id,
    project_title,
    job_id,
    job_status,
    before_path,
    after_path
FROM to_update
ORDER BY project_id;
SQL
    echo
    echo "[DRY-RUN] 실제 반영은 --apply 옵션으로 다시 실행하세요."
fi
