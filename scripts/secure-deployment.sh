#!/bin/bash
# ============================================================
# Aerial Survey Manager - 배포 보안 설정 스크립트
# 일반 사용자로부터 컨테이너/env 접근 제한
# ============================================================

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# root 권한 확인
check_root() {
    if [ "$EUID" -ne 0 ]; then
        log_error "이 스크립트는 root 권한으로 실행해야 합니다."
        echo "사용법: sudo ./scripts/secure-deployment.sh"
        exit 1
    fi
}

# 애플리케이션 사용자 생성
create_app_user() {
    log_info "애플리케이션 전용 사용자 설정..."

    APP_USER="aerial-app"

    # 사용자 존재 확인
    if id "$APP_USER" &>/dev/null; then
        log_info "사용자 $APP_USER 이미 존재함"
    else
        # 시스템 사용자 생성 (로그인 불가)
        useradd -r -s /sbin/nologin -d /nonexistent "$APP_USER"
        log_info "시스템 사용자 생성됨: $APP_USER"
    fi

    # docker 그룹에 추가
    usermod -aG docker "$APP_USER"
    log_info "$APP_USER 사용자를 docker 그룹에 추가함"
}

# .env 파일 보안 설정
secure_env_file() {
    log_info ".env 파일 권한 설정..."

    SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    ENV_FILE="$SCRIPT_DIR/.env"

    if [ -f "$ENV_FILE" ]; then
        # root만 읽기 가능하도록 설정
        chown root:root "$ENV_FILE"
        chmod 600 "$ENV_FILE"
        log_info ".env 파일 권한: root만 읽기 가능 (600)"
    else
        log_warn ".env 파일이 존재하지 않습니다: $ENV_FILE"
    fi
}

# Docker 소켓 보안 설정
secure_docker_socket() {
    log_info "Docker 소켓 권한 설정..."

    # Docker 소켓 권한 확인 (기본값 유지, 660은 너무 제한적일 수 있음)
    DOCKER_SOCKET="/var/run/docker.sock"
    if [ -S "$DOCKER_SOCKET" ]; then
        current_perms=$(stat -c "%a" "$DOCKER_SOCKET")
        log_info "현재 Docker 소켓 권한: $current_perms"

        echo ""
        echo "Docker 접근을 제한하려면 사용자를 docker 그룹에서 제거하세요:"
        echo "  sudo gpasswd -d [사용자명] docker"
        echo ""
    fi
}

# systemd 서비스 생성
create_systemd_service() {
    log_info "systemd 서비스 생성..."

    SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    SERVICE_FILE="/etc/systemd/system/aerial-survey.service"

    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Aerial Survey Manager
Documentation=https://github.com/your-org/aerial-survey-manager
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=$SCRIPT_DIR
EnvironmentFile=$SCRIPT_DIR/.env

# 서비스 시작: docker compose up
# 개발환경: docker-compose.prod.yml 우선, 배포 패키지: docker-compose.yml
ExecStart=/bin/bash -c 'if [ -f docker-compose.prod.yml ]; then /usr/bin/docker compose -f docker-compose.prod.yml up -d; else /usr/bin/docker compose up -d; fi'

# 서비스 중지: docker compose down
ExecStop=/bin/bash -c 'if [ -f docker-compose.prod.yml ]; then /usr/bin/docker compose -f docker-compose.prod.yml down; else /usr/bin/docker compose down; fi'

# 재시작 정책
Restart=on-failure
RestartSec=10

# 보안 설정
ProtectSystem=strict
ProtectHome=yes
NoNewPrivileges=yes
ReadWritePaths=$SCRIPT_DIR/data

[Install]
WantedBy=multi-user.target
EOF

    # 서비스 활성화
    systemctl daemon-reload
    systemctl enable aerial-survey.service

    log_info "systemd 서비스 생성 완료: aerial-survey.service"
    echo ""
    echo "서비스 관리 명령어:"
    echo "  시작: sudo systemctl start aerial-survey"
    echo "  중지: sudo systemctl stop aerial-survey"
    echo "  상태: sudo systemctl status aerial-survey"
    echo "  로그: sudo journalctl -u aerial-survey -f"
    echo ""
}

# 일반 사용자용 관리 스크립트 생성
create_user_scripts() {
    log_info "사용자용 관리 스크립트 생성..."

    SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
    BIN_DIR="/usr/local/bin"

    # 상태 확인 스크립트
    cat > "$BIN_DIR/aerial-status" << 'EOF'
#!/bin/bash
sudo systemctl status aerial-survey --no-pager
echo ""
echo "컨테이너 상태:"
sudo docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null | grep -E "^(NAMES|aerial)" || echo "실행 중인 컨테이너 없음"
EOF
    chmod +x "$BIN_DIR/aerial-status"

    # 재시작 스크립트
    cat > "$BIN_DIR/aerial-restart" << 'EOF'
#!/bin/bash
echo "Aerial Survey Manager 재시작 중..."
sudo systemctl restart aerial-survey
echo "완료. 상태 확인: aerial-status"
EOF
    chmod +x "$BIN_DIR/aerial-restart"

    # 로그 확인 스크립트
    cat > "$BIN_DIR/aerial-logs" << 'EOF'
#!/bin/bash
echo "=== Aerial Survey Manager 로그 ==="
echo "(종료: Ctrl+C)"
echo ""
sudo journalctl -u aerial-survey -f
EOF
    chmod +x "$BIN_DIR/aerial-logs"

    log_info "사용자 명령어 생성 완료:"
    echo "  aerial-status  : 서비스 상태 확인"
    echo "  aerial-restart : 서비스 재시작"
    echo "  aerial-logs    : 로그 실시간 확인"
    echo ""
}

# 배포 디렉토리 보안 설정
secure_deployment_dir() {
    log_info "배포 디렉토리 권한 설정..."

    SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

    # 민감한 파일 권한 설정
    find "$SCRIPT_DIR" -name "*.env*" -type f -exec chmod 600 {} \;
    find "$SCRIPT_DIR" -name "docker-compose*.yml" -type f -exec chmod 644 {} \;

    # SSL 디렉토리 보안
    if [ -d "$SCRIPT_DIR/ssl" ]; then
        chmod 700 "$SCRIPT_DIR/ssl"
        find "$SCRIPT_DIR/ssl" -type f -exec chmod 600 {} \;
        log_info "SSL 디렉토리 보안 설정 완료"
    fi

    log_info "배포 디렉토리 권한 설정 완료"
}

# sudoers 설정 (선택적)
setup_sudoers() {
    echo ""
    read -p "일반 사용자가 비밀번호 없이 aerial 명령어를 실행할 수 있게 하시겠습니까? (y/N): " allow_nopasswd

    if [[ "$allow_nopasswd" =~ ^[Yy]$ ]]; then
        SUDOERS_FILE="/etc/sudoers.d/aerial-survey"

        cat > "$SUDOERS_FILE" << 'EOF'
# Aerial Survey Manager - 일반 사용자 권한 설정
# 특정 systemctl 명령만 비밀번호 없이 허용

%users ALL=(ALL) NOPASSWD: /usr/bin/systemctl status aerial-survey
%users ALL=(ALL) NOPASSWD: /usr/bin/systemctl status aerial-survey --no-pager
%users ALL=(ALL) NOPASSWD: /usr/bin/systemctl restart aerial-survey
%users ALL=(ALL) NOPASSWD: /usr/bin/systemctl start aerial-survey
%users ALL=(ALL) NOPASSWD: /usr/bin/systemctl stop aerial-survey
%users ALL=(ALL) NOPASSWD: /usr/bin/journalctl -u aerial-survey *
%users ALL=(ALL) NOPASSWD: /usr/bin/docker ps --format *
EOF

        chmod 440 "$SUDOERS_FILE"
        log_info "sudoers 설정 완료: 비밀번호 없이 aerial 명령어 사용 가능"
    fi
}

# 설정 완료 메시지
print_completion() {
    echo ""
    echo -e "${GREEN}=============================================="
    echo "       보안 설정이 완료되었습니다!"
    echo "==============================================${NC}"
    echo ""
    echo -e "${BLUE}적용된 보안 설정:${NC}"
    echo "  1. .env 파일: root만 읽기 가능"
    echo "  2. systemd 서비스: aerial-survey.service"
    echo "  3. 사용자 명령어: aerial-status, aerial-restart, aerial-logs"
    echo ""
    echo -e "${YELLOW}일반 사용자는 다음 항목에 접근할 수 없습니다:${NC}"
    echo "  - .env 파일 내용"
    echo "  - docker 명령어 (docker 그룹에서 제거된 경우)"
    echo "  - 컨테이너 내부 환경변수"
    echo ""
    echo -e "${YELLOW}추가 보안을 위해:${NC}"
    echo "  1. 일반 사용자를 docker 그룹에서 제거:"
    echo "     sudo gpasswd -d [사용자명] docker"
    echo ""
    echo "  2. 로그아웃 후 재로그인 필요"
    echo ""
    echo -e "${BLUE}서비스 관리:${NC}"
    echo "  시작:   sudo systemctl start aerial-survey"
    echo "  중지:   sudo systemctl stop aerial-survey"
    echo "  상태:   aerial-status (일반 사용자 가능)"
    echo "  재시작: aerial-restart (일반 사용자 가능)"
    echo ""
}

# 메인 실행
main() {
    echo -e "${BLUE}"
    echo "=============================================="
    echo "  Aerial Survey Manager - 보안 설정"
    echo "=============================================="
    echo -e "${NC}"

    check_root
    create_app_user
    secure_env_file
    secure_docker_socket
    secure_deployment_dir
    create_systemd_service
    create_user_scripts
    setup_sudoers
    print_completion
}

main "$@"
