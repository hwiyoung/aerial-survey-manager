#!/bin/bash
#
# Aerial Survey Manager - 설치 스크립트
# 외부 기관 배포용
#

set -e

# 색상 정의
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 로고 출력
print_logo() {
    echo -e "${BLUE}"
    echo "=============================================="
    echo "     Aerial Survey Manager Installer"
    echo "           정사영상 생성 플랫폼"
    echo "=============================================="
    echo -e "${NC}"
}

# 로그 함수
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 시스템 요구사항 확인
check_requirements() {
    log_info "시스템 요구사항 확인 중..."

    # Docker 확인
    if ! command -v docker &> /dev/null; then
        log_error "Docker가 설치되어 있지 않습니다."
        echo "설치 방법: curl -fsSL https://get.docker.com | sh"
        exit 1
    fi
    log_info "Docker: $(docker --version)"

    # Docker Compose 확인
    if ! docker compose version &> /dev/null; then
        log_error "Docker Compose v2가 설치되어 있지 않습니다."
        echo "설치 방법: sudo apt-get install docker-compose-plugin"
        exit 1
    fi
    log_info "Docker Compose: $(docker compose version --short)"

    # NVIDIA 드라이버 확인
    if ! command -v nvidia-smi &> /dev/null; then
        log_warn "NVIDIA 드라이버가 감지되지 않았습니다."
        log_warn "GPU 처리를 위해 NVIDIA 드라이버를 설치하세요."
        read -p "GPU 없이 계속 진행하시겠습니까? (y/N): " continue_without_gpu
        if [[ ! "$continue_without_gpu" =~ ^[Yy]$ ]]; then
            exit 1
        fi
    else
        log_info "NVIDIA Driver: $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"

        # NVIDIA Container Toolkit 확인
        if ! docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
            log_error "NVIDIA Container Toolkit이 제대로 설정되지 않았습니다."
            echo "설치 방법은 docs/DEPLOYMENT_GUIDE.md를 참조하세요."
            exit 1
        fi
        log_info "NVIDIA Container Toolkit: 정상"
    fi

    # 디스크 용량 확인
    available_space=$(df -BG . | awk 'NR==2 {print $4}' | sed 's/G//')
    if [ "$available_space" -lt 100 ]; then
        log_warn "현재 디렉토리의 가용 공간이 ${available_space}GB입니다."
        log_warn "최소 100GB 이상의 공간을 권장합니다."
    fi

    log_info "시스템 요구사항 확인 완료"
    echo ""
}

# 랜덤 문자열 생성
generate_secret() {
    openssl rand -hex 32
}

generate_password() {
    openssl rand -base64 24 | tr -d '/+=' | head -c 24
}

# 환경 변수 설정
setup_environment() {
    log_info "환경 변수 설정 중..."

    if [ -f .env ]; then
        log_warn ".env 파일이 이미 존재합니다."
        read -p "기존 설정을 덮어쓰시겠습니까? (y/N): " overwrite
        if [[ ! "$overwrite" =~ ^[Yy]$ ]]; then
            log_info "기존 .env 파일을 유지합니다."
            return
        fi
        cp .env .env.backup.$(date +%Y%m%d%H%M%S)
        log_info "기존 설정이 백업되었습니다."
    fi

    # .env.production.example 복사
    if [ -f .env.production.example ]; then
        cp .env.production.example .env
    else
        cp .env.example .env
    fi

    echo ""
    echo -e "${BLUE}=== 필수 설정 입력 ===${NC}"
    echo ""

    # 도메인/IP 설정
    read -p "접속 도메인 또는 IP (예: app.example.com 또는 192.168.1.100): " domain
    if [ -z "$domain" ]; then
        domain="localhost"
    fi

    # 포트 설정
    read -p "웹 서비스 포트 [8081]: " web_port
    web_port=${web_port:-8081}

    # MINIO_PUBLIC_ENDPOINT 설정
    if [ "$web_port" = "80" ] || [ "$web_port" = "443" ]; then
        minio_endpoint="$domain"
    else
        minio_endpoint="$domain:$web_port"
    fi

    # 저장소 경로 설정
    echo ""
    echo -e "${YELLOW}저장소 경로 설정 (대용량 디스크 경로 권장)${NC}"
    read -p "처리 데이터 경로 [./data/processing]: " processing_path
    processing_path=${processing_path:-./data/processing}

    read -p "MinIO 저장소 경로 [./data/minio]: " minio_path
    minio_path=${minio_path:-./data/minio}

    # Metashape 라이선스
    echo ""
    read -p "Metashape 라이선스 키 (없으면 Enter): " metashape_license

    # 비밀번호 자동 생성
    echo ""
    log_info "보안 키 및 비밀번호 자동 생성 중..."

    postgres_password=$(generate_password)
    jwt_secret=$(generate_secret)
    minio_access_key="aerial-admin"
    minio_secret_key=$(generate_password)

    # .env 파일 업데이트
    sed -i "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$postgres_password|" .env
    sed -i "s|^JWT_SECRET_KEY=.*|JWT_SECRET_KEY=$jwt_secret|" .env
    sed -i "s|^MINIO_ACCESS_KEY=.*|MINIO_ACCESS_KEY=$minio_access_key|" .env
    sed -i "s|^MINIO_SECRET_KEY=.*|MINIO_SECRET_KEY=$minio_secret_key|" .env
    sed -i "s|^MINIO_PUBLIC_ENDPOINT=.*|MINIO_PUBLIC_ENDPOINT=$minio_endpoint|" .env
    sed -i "s|^PROCESSING_DATA_PATH=.*|PROCESSING_DATA_PATH=$processing_path|" .env
    sed -i "s|^MINIO_DATA_PATH=.*|MINIO_DATA_PATH=$minio_path|" .env
    sed -i "s|^METASHAPE_LICENSE_KEY=.*|METASHAPE_LICENSE_KEY=$metashape_license|" .env

    # 도메인 설정 추가
    if ! grep -q "^DOMAIN=" .env; then
        echo "DOMAIN=$domain" >> .env
    else
        sed -i "s|^DOMAIN=.*|DOMAIN=$domain|" .env
    fi

    # 저장소 디렉토리 생성
    mkdir -p "$processing_path"
    mkdir -p "$minio_path"

    echo ""
    log_info "환경 설정 완료"
    echo ""
    echo -e "${YELLOW}=== 생성된 인증 정보 (안전하게 보관하세요) ===${NC}"
    echo "PostgreSQL 비밀번호: $postgres_password"
    echo "MinIO Access Key: $minio_access_key"
    echo "MinIO Secret Key: $minio_secret_key"
    echo ""
}

# nginx 설정 업데이트
setup_nginx() {
    log_info "Nginx 설정 중..."

    # 도메인 읽기
    domain=$(grep "^DOMAIN=" .env | cut -d'=' -f2)

    # nginx.conf 또는 nginx.prod.conf 업데이트
    if [ -f nginx.conf ]; then
        sed -i "s|server_name .*;|server_name $domain;|" nginx.conf
        log_info "nginx.conf 도메인 설정 완료: $domain"
    elif [ -f nginx.prod.conf ]; then
        sed -i "s|server_name .*;|server_name $domain;|" nginx.prod.conf
        log_info "nginx.prod.conf 도메인 설정 완료: $domain"
    fi
}

# SSL 설정
setup_ssl() {
    echo ""
    read -p "SSL/HTTPS를 설정하시겠습니까? (y/N): " setup_ssl_choice

    if [[ "$setup_ssl_choice" =~ ^[Yy]$ ]]; then
        mkdir -p ssl

        echo "SSL 인증서 설정 방법:"
        echo "1) Let's Encrypt (자동 발급)"
        echo "2) 기존 인증서 파일 사용"
        echo "3) 나중에 설정"
        read -p "선택 [3]: " ssl_choice
        ssl_choice=${ssl_choice:-3}

        case $ssl_choice in
            1)
                domain=$(grep "^DOMAIN=" .env | cut -d'=' -f2)
                log_info "Let's Encrypt 인증서 발급을 위해 서비스를 중지합니다..."
                docker compose down 2>/dev/null || true

                if command -v certbot &> /dev/null; then
                    sudo certbot certonly --standalone -d "$domain"
                    sudo cp "/etc/letsencrypt/live/$domain/fullchain.pem" ./ssl/cert.pem
                    sudo cp "/etc/letsencrypt/live/$domain/privkey.pem" ./ssl/key.pem
                    sudo chown $USER:$USER ./ssl/*.pem
                    log_info "SSL 인증서 발급 완료"
                else
                    log_error "certbot이 설치되어 있지 않습니다."
                    log_info "설치: sudo apt-get install certbot"
                fi
                ;;
            2)
                read -p "인증서 파일 경로 (cert.pem): " cert_path
                read -p "개인키 파일 경로 (key.pem): " key_path

                if [ -f "$cert_path" ] && [ -f "$key_path" ]; then
                    cp "$cert_path" ./ssl/cert.pem
                    cp "$key_path" ./ssl/key.pem
                    log_info "SSL 인증서 복사 완료"
                else
                    log_error "인증서 파일을 찾을 수 없습니다."
                fi
                ;;
            *)
                log_info "SSL 설정을 건너뜁니다."
                ;;
        esac
    fi
}

# Docker 이미지 빌드 및 서비스 시작
start_services() {
    # 프로덕션 compose 파일 사용
    compose_file="docker-compose.yml"
    if [ -f "docker-compose.prod.yml" ]; then
        compose_file="docker-compose.prod.yml"
    fi

    # 배포 패키지인지 확인 (images 디렉토리 존재)
    if [ -d "images" ]; then
        # 배포 패키지: 이미지 로드 확인
        log_info "배포 패키지 감지됨"

        # 이미지가 로드되었는지 확인
        if ! docker images | grep -q "aerial-survey-manager"; then
            log_warn "Docker 이미지가 로드되지 않았습니다."
            log_info "이미지 로드 중..."
            ./load-images.sh
        else
            log_info "Docker 이미지: 로드됨"
        fi
    else
        # 소스 코드: 이미지 빌드
        log_info "Docker 이미지 빌드 중... (최초 실행 시 시간이 소요됩니다)"
        docker compose -f "$compose_file" build
    fi

    log_info "서비스 시작 중..."
    docker compose -f "$compose_file" up -d

    log_info "서비스 초기화 대기 중..."
    sleep 10
}

# 헬스체크
run_healthcheck() {
    log_info "서비스 상태 확인 중..."

    # 헬스체크 스크립트가 있으면 실행
    if [ -f "scripts/healthcheck.sh" ]; then
        bash scripts/healthcheck.sh
    else
        # 기본 헬스체크
        echo ""
        docker compose ps
        echo ""

        # API 헬스체크
        if curl -s http://localhost:8081/health > /dev/null 2>&1; then
            log_info "API 서버: 정상"
        else
            log_warn "API 서버: 응답 없음 (초기화 중일 수 있습니다)"
        fi
    fi
}

# 설치 완료 메시지
print_completion() {
    domain=$(grep "^DOMAIN=" .env | cut -d'=' -f2)
    web_port=$(grep "^WEB_PORT=" .env | cut -d'=' -f2)
    web_port=${web_port:-8081}

    echo ""
    echo -e "${GREEN}=============================================="
    echo "         설치가 완료되었습니다!"
    echo "==============================================${NC}"
    echo ""
    echo -e "${BLUE}접속 정보:${NC}"
    echo "  웹 UI: http://$domain:$web_port"
    echo "  API 문서: http://$domain:$web_port/api/v1/docs"
    echo ""
    echo -e "${BLUE}관리 도구:${NC}"
    echo "  Flower (작업 모니터링): http://localhost:5555"
    echo "  MinIO Console: http://localhost:9003"
    echo ""
    echo -e "${YELLOW}다음 단계:${NC}"
    echo "  1. 웹 UI에 접속하여 관리자 계정 생성"
    echo "  2. 테스트 프로젝트 생성 및 이미지 업로드 테스트"
    echo "  3. 처리 기능 테스트"
    echo ""
    echo -e "${BLUE}유용한 명령어:${NC}"
    echo "  서비스 상태: docker compose ps"
    echo "  로그 확인: docker compose logs -f"
    echo "  서비스 재시작: docker compose restart"
    echo "  서비스 중지: docker compose down"
    echo ""
}

# 메인 실행
main() {
    print_logo

    # 스크립트 위치로 이동
    cd "$(dirname "$0")/.."

    check_requirements
    setup_environment
    setup_nginx
    setup_ssl
    start_services
    run_healthcheck
    print_completion
}

# 스크립트 실행
main "$@"
