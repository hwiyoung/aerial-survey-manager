#!/bin/bash
#
# Aerial Survey Manager - 처리 운영 점검 스크립트 (4차 스프린트)
# 처리 엔진 정책, 큐 적재량, 워커 상태를 빠르게 확인합니다.
#

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
BLUE='\033[0;34m'
NC='\033[0m'

PASS=0
WARN=0
FAIL=0

log_ok() { echo -e "  ${GREEN}✓${NC} $1"; ((PASS++)); }
log_warn() { echo -e "  ${YELLOW}!${NC} $1"; ((WARN++)); }
log_fail() { echo -e "  ${RED}✗${NC} $1"; ((FAIL++)); }

repo_root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$repo_root"
ENV_FILE="${repo_root}/.env"

get_env() {
  local key="$1"
  local value=""
  if [ -f "$ENV_FILE" ]; then
    value="$(awk -F'=' -v key="$key" '$1==key {print $2; exit}' "$ENV_FILE" | tr -d '\r')"
  fi
  printf '%s' "${value}"
}

to_bool() {
  case "${1,,}" in
    true|1|yes|y|on) return 0 ;;
    *) return 1 ;;
  esac
}

is_enabled() {
  local raw
  raw="$(get_env "$1")"
  to_bool "${raw:-}" || return 1
}

compose_file="docker-compose.yml"
if [ -f "docker-compose.prod.yml" ]; then
  compose_file="docker-compose.prod.yml"
fi

compose_file="${COMPOSE_FILE:-$compose_file}"

if ! docker compose -f "$compose_file" version >/dev/null 2>&1; then
  log_warn "현재 docker-compose 파일을 읽을 수 없습니다: $compose_file"
fi

metashape_flag="$(get_env "ENABLE_METASHAPE_ENGINE")"
odm_flag="$(get_env "ENABLE_ODM_ENGINE")"
external_flag="$(get_env "ENABLE_EXTERNAL_ENGINE")"
external_cog="$(get_env "ENABLE_EXTERNAL_COG_INGEST")"
backend_candidates="$(get_env "BACKEND_DIAGNOSTIC_PORTS")"
backend_default_port="${BACKEND_DEFAULT_PORT:-}"
if [ -z "${backend_default_port}" ]; then
  if [ -n "${backend_candidates}" ]; then
    backend_default_port="$backend_candidates"
  else
    backend_default_port="8001"
  fi
fi

echo ""
echo -e "${BLUE}=============================================="
echo "    Processing Operation Diagnostics"
echo "==============================================${NC}"
echo ""

# 1) 엔진 정책 확인
echo -e "${BLUE}[1] Processing Engine Policy${NC}"
if [ -f ".env" ]; then
  metashape="$metashape_flag"
  odm="$odm_flag"
  external="$external_flag"
  external_cog="$external_cog"

  if [ -n "${metashape:-}" ] || [ -n "${odm:-}" ] || [ -n "${external:-}" ]; then
    echo "  metashape=$metashape"
    echo "  odm=$odm"
    echo "  external=$external"
    echo "  external_cog_ingest=$external_cog"
    log_ok "엔진 정책 환경변수 확인 완료"
  else
    log_warn ".env에서 ENABLE_*_ENGINE 값이 확인되지 않습니다"
  fi
else
  log_fail ".env 파일이 없습니다"
fi
echo ""

# 2) API 엔진 노출 상태 (인증 없이 접근 가능한 네트워크 정책이면)
echo -e "${BLUE}[2] Processing API Contract${NC}"
api_token="${API_TOKEN:-}"
if [ -z "$api_token" ] && [ -n "$(get_env ADMIN_EMAIL)" ] && [ -n "$(get_env ADMIN_PASSWORD)" ]; then
  login_payload="$(cat <<JSON
{"email":"$(get_env ADMIN_EMAIL)","password":"$(get_env ADMIN_PASSWORD)"}
JSON
)"
  api_token="$(curl -sS --max-time 3 -H 'Content-Type: application/json' -d "$login_payload" "http://localhost:$backend_default_port/api/v1/auth/login" | python3 -c 'import sys, json; data=json.load(sys.stdin); print(data.get(\"access_token\", \"\"))' 2>/dev/null || true)"
fi

api_auth_header=()
if [ -n "$api_token" ]; then
  api_auth_header=(-H "Authorization: Bearer $api_token")
fi

found_api=false
IFS=',' read -r -a api_ports <<< "${backend_default_port}"
if [ ${#api_ports[@]} -eq 0 ]; then
  api_ports=(8001 8081)
fi

for port in "${api_ports[@]}"; do
  port="$(echo "$port" | tr -d '[:space:]')"
  if [ -z "$port" ]; then
    continue
  fi
  if curl -sSf --max-time 3 "${api_auth_header[@]:-}" "http://localhost:${port}/api/v1/processing/engines" > /tmp/processing_engines.json 2>/dev/null; then
    found_api=true
    break
  fi
done

if [ "$found_api" = true ]; then
  echo "  /api/v1/processing/engines 응답 수신"
  log_ok "/api/v1/processing/engines 접근 가능"
  if command -v jq >/dev/null 2>&1; then
    jq '.default_engine, .engines | map(select(.enabled == false) | .name)' /tmp/processing_engines.json | sed 's/^/  /'
  else
    head -n 3 /tmp/processing_engines.json | sed 's/^/  /'
  fi
else
  log_warn "/api/v1/processing/engines 직접 호출 실패 (인증/네트워크 정책 또는 서비스 미기동)"
fi
echo ""

# 3) 큐 상태 확인
echo -e "${BLUE}[3] Queue Backlog Check${NC}"
if ! docker compose -f "$compose_file" exec -T redis redis-cli ping >/dev/null 2>&1; then
  log_fail "redis ping 실패 (Redis 미기동)"
else
  for queue in metashape odm external; do
    enabled=true
    if [ "$queue" = "metashape" ] && ! is_enabled "ENABLE_METASHAPE_ENGINE"; then
      enabled=false
    fi
    if [ "$queue" = "odm" ] && ! is_enabled "ENABLE_ODM_ENGINE"; then
      enabled=false
    fi
    if [ "$queue" = "external" ] && ! is_enabled "ENABLE_EXTERNAL_ENGINE"; then
      enabled=false
    fi

    if [ "$enabled" = false ]; then
      if docker compose -f "$compose_file" exec -T redis redis-cli llen "$queue" >/dev/null 2>&1; then
        log_warn "redis 큐 '$queue'는 비활성 정책이나 잔여 작업이 존재할 수 있습니다"
      else
        log_ok "redis 큐 '$queue' 비활성(정책)"
      fi
      continue
    fi

    if result="$(docker compose -f "$compose_file" exec -T redis redis-cli llen "$queue" 2>/dev/null)"; then
      if [ "$result" -gt 20 ]; then
        log_warn "redis 큐 '$queue' 길이: $result (과다)"
      else
        log_ok "redis 큐 '$queue' 길이: $result"
      fi
    else
      log_fail "redis 큐 '$queue' 조회 실패 (Redis 미기동 또는 queue 없음)"
    fi
  done
fi
echo ""

# 4) 워커/서비스 상태 확인
echo -e "${BLUE}[4] Service / Worker State${NC}"
services="$(docker compose -f "$compose_file" ps --services 2>/dev/null || true)"
for svc in backend worker-engine; do
  if echo "$services" | grep -q "^$svc$"; then
    status="$(docker compose -f "$compose_file" ps "$svc" --format "{{.State}}" 2>/dev/null | tr -d '[:space:]')"
    if [ "$status" = "running" ] || [ "$status" = "Up" ] || [[ "$status" == "Up"* ]]; then
      log_ok "service $svc: running"
    else
      log_fail "service $svc: $status"
    fi
  else
    log_fail "service $svc: 미정의(구성 불일치)"
  fi
done

if is_enabled "ENABLE_ODM_ENGINE" && echo "$services" | grep -q '^worker-odm$'; then
  status="$(docker compose -f "$compose_file" ps worker-odm --format "{{.State}}" 2>/dev/null | tr -d '[:space:]')"
  if [ "$status" = "running" ] || [ "$status" = "Up" ] || [[ "$status" == "Up"* ]]; then
    log_ok "service worker-odm: running"
  else
    log_warn "service worker-odm: $status (비활성 큐라도 필요 시 점검)"
  fi
elif is_enabled "ENABLE_ODM_ENGINE"; then
  log_fail "service worker-odm: 미정의인데 ODM이 ON"
fi

if docker compose -f "$compose_file" exec -T backend celery -A app.workers.tasks inspect ping >/dev/null 2>&1; then
  log_ok "celery ping (backend)"
else
  log_warn "celery ping 실패 (backend or worker 미연결)"
fi
echo ""

# 5) 정책 불일치 가이드
echo -e "${BLUE}[5] Policy mismatch quick hints${NC}"
if [ "${metashape:-}" = "false" ] && [ "$FAIL" -eq 0 ]; then
  echo "  메타스페이스 비활성화: worker-engine이 실행되지 않아도 정책 위반은 아닙니다."
fi
if [ "${external:-}" = "true" ] && [ "${odm:-}" = "false" ]; then
  echo "  external만 활성일 경우 external 큐/worker 조합을 별도 점검하세요."
fi

echo ""
echo -e "${BLUE}----------------------------------------------"
echo -e "Result ${GREEN}PASS${NC}: $PASS, ${YELLOW}WARN${NC}: $WARN, ${RED}FAIL${NC}: $FAIL"
echo "----------------------------------------------${NC}"

if [ "$FAIL" -gt 0 ]; then
  exit 1
fi
