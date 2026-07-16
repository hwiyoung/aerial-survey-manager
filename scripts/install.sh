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

find_packaged_worker_engine_image() {
    local compose_image
    if [ -f docker-compose.yml ]; then
        compose_image=$(docker compose config --images 2>/dev/null \
            | grep -E '^aerial-survey-manager:worker-engine-' \
            | head -n 1 || true)
        if [ -n "$compose_image" ]; then
            echo "$compose_image"
            return 0
        fi
    fi

    docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null \
        | grep -E '^(aerial-survey-manager:worker-engine-|aerial-prod-worker-engine:latest$)' \
        | sort -r \
        | head -n 1
}

test_docker_gpu_runtime() {
    local test_image
    test_image=$(find_packaged_worker_engine_image || true)

    if [ -n "$test_image" ]; then
        log_info "Docker GPU 전달 테스트 이미지: $test_image"
        docker run --rm --gpus all --entrypoint nvidia-smi "$test_image" -L &>/dev/null
        return $?
    fi

    # Fallback for source installs where release images were not loaded.
    docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi &>/dev/null
}

check_kernel_nvidia_modules() {
    local kernel
    kernel="$(uname -r 2>/dev/null || true)"
    if [ -z "$kernel" ] || ! command -v dpkg-query >/dev/null 2>&1; then
        return 0
    fi

    local matched
    matched="$(
        dpkg-query -W -f='${binary:Package}\t${db:Status-Abbrev}\n' 'linux-modules-nvidia-*' 2>/dev/null \
            | awk -v k="$kernel" '$2 ~ /^ii/ && index($1, k) {print $1}'
    )"
    if [ -n "$matched" ]; then
        log_info "현재 커널 NVIDIA 모듈 패키지: $(printf '%s' "$matched" | paste -sd ',' -)"
    else
        log_warn "현재 커널($kernel)에 대응하는 linux-modules-nvidia-* 패키지를 찾지 못했습니다."
        log_warn "커널/NVIDIA 모듈 mismatch이면 nvidia-smi와 worker-engine이 실패합니다."
        log_warn "상세 진단: ./scripts/check-gpu-stack.sh"
    fi
}

validate_compose_config() {
    local compose_file="$1"
    log_info "docker compose config 검증 중: $compose_file"
    docker compose -f "$compose_file" config >/dev/null
    log_info "docker compose config: 정상"
}

validate_nginx_config() {
    local nginx_file="nginx.conf"
    if [ -f nginx.prod.conf ]; then
        nginx_file="nginx.prod.conf"
    fi

    if [ ! -d ssl ]; then
        log_warn "ssl 디렉토리가 없어 nginx -t 검증을 건너뜁니다."
        return 0
    fi

    log_info "nginx -t 검증 중: $nginx_file"
    docker run --rm \
        -v "$PWD/$nginx_file:/etc/nginx/nginx.conf:ro" \
        -v "$PWD/ssl:/etc/nginx/ssl:ro" \
        nginx:alpine nginx -t >/tmp/aerial-nginx-test.log 2>&1 \
        || {
            cat /tmp/aerial-nginx-test.log
            rm -f /tmp/aerial-nginx-test.log
            return 1
        }
    rm -f /tmp/aerial-nginx-test.log
    log_info "nginx -t: 정상"
}

upsert_env() {
    local key="$1"
    local value="$2"
    if grep -q "^${key}=" .env; then
        sed -i "s|^${key}=.*|${key}=${value}|" .env
    else
        echo "${key}=${value}" >> .env
    fi
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
        if command -v nvidia-ctk &> /dev/null; then
            log_info "NVIDIA Container Toolkit: $(nvidia-ctk --version 2>&1 | head -1)"
        elif docker info 2>/dev/null | grep -qi "nvidia"; then
            log_info "NVIDIA Container Toolkit: 정상 (docker runtime 확인됨)"
        else
            log_warn "NVIDIA Container Toolkit이 감지되지 않았습니다."
            echo "설치 방법은 docs/DEPLOYMENT_GUIDE.md를 참조하세요."
            read -p "Container Toolkit 없이 계속 진행하시겠습니까? (y/N): " continue_without_toolkit
            if [[ ! "$continue_without_toolkit" =~ ^[Yy]$ ]]; then
                exit 1
            fi
        fi

        # docker info의 runtime 목록과 관계없이 실제 컨테이너 전달을 검증합니다.
        log_info "Docker GPU 전달 테스트 중..."
        if test_docker_gpu_runtime; then
            log_info "Docker GPU 전달: 정상"
        else
            log_warn "Docker에서 GPU를 사용할 수 없습니다."
            if command -v nvidia-ctk &> /dev/null; then
                log_warn "복구를 진행하면 Docker가 재시작되어 실행 중인 모든 컨테이너가 잠시 중단됩니다."
                read -r -p "NVIDIA runtime을 재등록하고 Docker를 재시작하시겠습니까? (y/N): " repair_gpu_runtime
                if [[ "$repair_gpu_runtime" =~ ^[Yy]$ ]]; then
                    log_info "NVIDIA runtime 재등록 및 Docker 재시작 중..."
                    if sudo nvidia-ctk runtime configure --runtime=docker \
                        && sudo systemctl restart docker \
                        && test_docker_gpu_runtime; then
                        log_info "Docker GPU 전달: 복구 완료"
                    else
                        log_warn "Docker GPU 전달 자동 복구에 실패했습니다."
                    fi
                fi
            fi

            if ! test_docker_gpu_runtime; then
                log_warn "Docker GPU 전달 실패. GPU 처리 기능을 사용할 수 없습니다."
                read -r -p "GPU 없이 계속 진행하시겠습니까? (y/N): " continue_without_gpu_docker
                if [[ ! "$continue_without_gpu_docker" =~ ^[Yy]$ ]]; then
                    exit 1
                fi
            fi
        fi

        log_info "NVIDIA Persistence Mode 설정 중..."
        sudo systemctl enable --now nvidia-persistenced 2>/dev/null || true
        sudo nvidia-smi -pm 1 2>/dev/null || true
        check_kernel_nvidia_modules
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

prompt_initial_admin_credentials() {
    local requested_email
    local requested_password
    local confirmed_password

    echo ""
    echo -e "${YELLOW}최초 관리자 계정 설정${NC}"
    echo "기존 DB에 사용자가 있으면 계정을 새로 만들거나 비밀번호를 변경하지 않습니다."

    while true; do
        read -r -p "최초 관리자 아이디 [admin]: " requested_email
        requested_email=${requested_email:-admin}
        if [[ "$requested_email" =~ ^[A-Za-z0-9._@+-]+$ ]]; then
            admin_email="$requested_email"
            break
        fi
        log_warn "관리자 아이디에는 영문, 숫자, ., _, @, +, -만 사용할 수 있습니다."
    done

    while true; do
        read -r -s -p "최초 관리자 비밀번호 (자동 생성하려면 Enter): " requested_password
        echo ""

        if [ -z "$requested_password" ]; then
            admin_password=$(generate_password)
            admin_password_generated=true
            log_info "최초 관리자 비밀번호를 자동 생성했습니다."
            break
        fi

        if [ "${#requested_password}" -lt 12 ]; then
            log_warn "관리자 비밀번호는 12자 이상이어야 합니다."
            continue
        fi

        if [[ ! "$requested_password" =~ ^[A-Za-z0-9._~!@%^*+=:,/?-]+$ ]]; then
            log_warn "비밀번호에는 공백, 따옴표, #, $, &, |, 역슬래시를 사용할 수 없습니다."
            continue
        fi

        read -r -s -p "관리자 비밀번호 확인: " confirmed_password
        echo ""
        if [ "$requested_password" != "$confirmed_password" ]; then
            log_warn "입력한 비밀번호가 일치하지 않습니다."
            continue
        fi

        admin_password="$requested_password"
        admin_password_generated=false
        break
    done
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
    # 기본값은 내부망 접속 허용입니다. 배포PC에서만 접속하게 제한하려면
    # HOST_BIND를 127.0.0.1로 변경하세요.
    read -p "접속 도메인 또는 IP [localhost]: " domain
    domain=${domain:-localhost}

    read -p "호스트 바인드 주소 [0.0.0.0]: " host_bind
    host_bind=${host_bind:-0.0.0.0}

    # 포트 설정 (nginx/web 진입점 하나만 공개)
    read -p "웹 서비스 포트 [18100]: " web_port
    web_port=${web_port:-18100}

    # 저장소 경로 설정
    echo ""
    echo -e "${YELLOW}저장소 경로 설정 (대용량 디스크 경로 권장)${NC}"
    echo "신규 설치는 기준 경로 하나를 정하면 하위 폴더가 자동으로 정리됩니다."
    read -p "데이터 기준 경로 [./data]: " data_root
    data_root=${data_root:-./data}

    read -p "프로젝트/처리 데이터 경로 [$data_root/projects]: " processing_path
    processing_path=${processing_path:-$data_root/projects}

    read -p "로컬 스토리지 기준 경로 [$data_root]: " storage_path
    storage_path=${storage_path:-$data_root}

    read -p "최종 정사영상 경로 [$data_root/orthomosaic]: " export_path
    export_path=${export_path:-$data_root/orthomosaic}

    read -p "MinIO 데이터 경로 [$data_root/minio]: " minio_path
    minio_path=${minio_path:-$data_root/minio}

    # 오프라인 타일맵 설정
    echo ""
    echo -e "${YELLOW}오프라인 지도 타일 설정${NC}"
    echo "이 배포 패키지는 오프라인 지도 모드로 빌드됩니다."
    echo "지도 배경이 필요하면 타일 데이터를 아래 경로에 준비하세요."
    USE_OFFLINE_TILES="true"
    read -p "타일 데이터 경로 [$data_root/tiles]: " tiles_path
    if [ -z "$tiles_path" ]; then
        tiles_path="$data_root/tiles"
        log_warn "기본 경로 사용: $tiles_path"
    fi

    # 타일 경로 확인
    if [ ! -d "$tiles_path" ]; then
        log_warn "타일 디렉토리가 존재하지 않습니다: $tiles_path"
        read -p "디렉토리를 생성하시겠습니까? (Y/n): " create_tiles_dir
        if [[ ! "$create_tiles_dir" =~ ^[Nn]$ ]]; then
            mkdir -p "$tiles_path"
            log_info "타일 디렉토리 생성됨: $tiles_path"
            echo "타일 데이터를 이 경로에 복사하세요: $tiles_path/{z}/{x}/{y}.png (또는 .jpg)"
        fi
    else
        # 타일 파일 존재 확인 (png, jpg, jpeg 지원)
        tile_count=$(find "$tiles_path" \( -name "*.png" -o -name "*.jpg" -o -name "*.jpeg" \) 2>/dev/null | head -10 | wc -l)
        if [ "$tile_count" -gt 0 ]; then
            log_info "타일 데이터 확인됨: $tiles_path"
        else
            log_warn "타일 디렉토리는 있지만 이미지 파일이 없습니다."
            echo "타일 데이터를 이 경로에 복사하세요: $tiles_path/{z}/{x}/{y}.png (또는 .jpg)"
        fi
    fi

    # 처리 엔진 라이선스
    echo ""
    echo -e "${YELLOW}GPU 처리 엔진 설정${NC}"
    echo "정사영상 처리에 필요합니다. 나중에 .env에서 설정할 수도 있습니다."
    read -p "처리 엔진 라이선스 키 (나중에 설정하려면 Enter): " engine_license
    if [ -z "$engine_license" ]; then
        log_warn "라이선스 키 없이 설치합니다. 처리 기능은 .env의 ENGINE_LICENSE_KEY 설정 후 사용 가능합니다."
    fi

    # 내부 보안 값은 자동 생성하고, 최초 관리자 비밀번호는 사용자가
    # 직접 입력하거나 Enter를 눌러 자동 생성할 수 있습니다.
    echo ""
    log_info "내부 보안 키 자동 생성 중..."

    postgres_password=$(generate_password)
    jwt_secret=$(generate_secret)
    prompt_initial_admin_credentials

    # .env 파일 업데이트
    upsert_env "POSTGRES_PASSWORD" "$postgres_password"
    upsert_env "JWT_SECRET_KEY" "$jwt_secret"
    upsert_env "ALLOW_WEAK_JWT_SECRET" "false"
    upsert_env "ADMIN_EMAIL" "$admin_email"
    upsert_env "ADMIN_PASSWORD" "$admin_password"
    upsert_env "ADMIN_NAME" "관리자"
    upsert_env "AERIAL_DATA_ROOT" "$data_root"
    upsert_env "PROCESSING_DATA_PATH" "$processing_path"
    upsert_env "LOCAL_STORAGE_PATH" "$storage_path"
    upsert_env "EXPORT_ROOT_PATH" "$export_path"
    upsert_env "AUTO_EXPORT_ENABLED" "false"
    upsert_env "AUTO_EXPORT_TARGET_CRS" "EPSG:5186"
    upsert_env "MINIO_DATA_PATH" "$minio_path"
    upsert_env "ENGINE_LICENSE_KEY" "$engine_license"
    upsert_env "HOST_BIND" "$host_bind"
    upsert_env "AERIAL_WEB_PORT" "$web_port"
    upsert_env "MINIO_PUBLIC_ENDPOINT" "$domain:$web_port"

    # 도메인 설정
    upsert_env "DOMAIN" "$domain"

    # 타일 경로 설정
    upsert_env "TILES_PATH" "$tiles_path"

    # 오프라인 지도 사용 여부 설정
    upsert_env "USE_OFFLINE_TILES" "$USE_OFFLINE_TILES"
    upsert_env "VITE_MAP_OFFLINE" "$USE_OFFLINE_TILES"
    upsert_env "VITE_TILE_URL" "/tiles/{z}/{x}/{y}"

    # 저장소 디렉토리 생성
    mkdir -p "$processing_path"
    mkdir -p "$storage_path"
    mkdir -p "$storage_path/projects"
    mkdir -p "$export_path"
    mkdir -p "$minio_path"
    mkdir -p "$tiles_path"

    echo ""
    log_info "환경 설정 완료"
    echo ""
    echo -e "${YELLOW}=== 최초 관리자 로그인 정보 ===${NC}"
    echo "관리자 아이디: $admin_email"
    if [ "$admin_password_generated" = "true" ]; then
        echo "관리자 비밀번호: $admin_password"
        echo "자동 생성된 비밀번호는 지금 안전한 곳에 보관하세요."
    else
        echo "관리자 비밀번호: 설치 중 직접 입력한 값"
    fi
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

    validate_compose_config "$compose_file"
    validate_nginx_config

    log_info "서비스 시작 중..."
    COMPOSE_FILE="$compose_file" ./scripts/systemd-start.sh

    log_info "서비스 초기화 대기 중..."
    sleep 10
}

# 별도 드라이브 사용 시 Docker 부팅 순서 설정
setup_mount_dependency() {
    mount_points=()
    root_device=$(df / 2>/dev/null | awk 'NR==2 {print $1}')

    for key in AERIAL_DATA_ROOT LOCAL_STORAGE_PATH PROCESSING_DATA_PATH EXPORT_ROOT_PATH TILES_PATH MINIO_DATA_PATH; do
        path=$(grep "^${key}=" .env | cut -d'=' -f2-)
        if [ -z "$path" ] || [[ ! "$path" = /* ]]; then
            continue
        fi

        device=$(df "$path" 2>/dev/null | awk 'NR==2 {print $1}')
        if [ -z "$device" ] || [ "$device" = "$root_device" ]; then
            continue
        fi

        mount_point=$(df "$path" 2>/dev/null | awk 'NR==2 {print $6}')
        if [ -z "$mount_point" ] || [ "$mount_point" = "/" ]; then
            continue
        fi

        duplicate=false
        for existing in "${mount_points[@]}"; do
            if [ "$existing" = "$mount_point" ]; then
                duplicate=true
                break
            fi
        done
        if [ "$duplicate" = "false" ]; then
            mount_points+=("$mount_point")
        fi
    done

    if [ "${#mount_points[@]}" -eq 0 ]; then
        return
    fi

    requires_mounts="${mount_points[*]}"

    echo ""
    log_info "데이터 경로가 별도 드라이브에 있습니다: $requires_mounts"
    log_info "시스템 재부팅 시 드라이브 마운트 후 Docker가 시작되도록 설정합니다."

    # 이미 설정되어 있는지 확인
    all_configured=true
    for mount_point in "${mount_points[@]}"; do
        if ! systemctl cat docker.service 2>/dev/null | grep -q "RequiresMountsFor.*$mount_point"; then
            all_configured=false
            break
        fi
    done
    if [ "$all_configured" = "true" ]; then
        log_info "Docker 부팅 순서: 이미 설정됨"
        return
    fi

    # systemd override 생성 (sudo 필요)
    override_dir="/etc/systemd/system/docker.service.d"
    override_file="$override_dir/aerial-survey-mounts.conf"

    # systemd override 생성 (root 권한 필요)
    if [ "$(id -u)" = "0" ]; then
        mkdir -p "$override_dir"
        cat > "$override_file" << EOF
[Unit]
RequiresMountsFor=$requires_mounts
EOF
        systemctl daemon-reload
        log_info "Docker 부팅 순서 설정 완료: $requires_mounts 마운트 후 Docker 시작"
    else
        log_warn "Docker 부팅 순서 설정에 root 권한이 필요합니다."
        log_warn "다음 명령을 실행하세요:"
        echo ""
        echo "  sudo mkdir -p $override_dir"
        echo "  echo -e '[Unit]\nRequiresMountsFor=$requires_mounts' | sudo tee $override_file"
        echo "  sudo systemctl daemon-reload"
        echo ""
    fi
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
        host_bind=$(grep "^HOST_BIND=" .env 2>/dev/null | cut -d'=' -f2)
        web_port=$(grep "^AERIAL_WEB_PORT=" .env 2>/dev/null | cut -d'=' -f2)
        health_host=${host_bind:-127.0.0.1}
        web_port=${web_port:-18100}
        if [ "$health_host" = "0.0.0.0" ]; then
            health_host="127.0.0.1"
        fi
        if curl -s "http://$health_host:$web_port/health" > /dev/null 2>&1; then
            log_info "API 서버: 정상"
        else
            log_warn "API 서버: 응답 없음 (초기화 중일 수 있습니다)"
        fi
    fi
}

# 네트워크 고정 IP 설정
setup_network() {
    echo ""
    echo -e "${YELLOW}=== 네트워크 설정 ===${NC}"
    echo "서버의 위치를 옮기거나 안정적인 접속을 위해 고정 IP를 설정할 수 있습니다."
    echo ""
    read -p "고정 IP를 설정하시겠습니까? (y/N): " setup_static_ip

    if [[ "$setup_static_ip" =~ ^[Yy]$ ]]; then
        if [ -f "scripts/configure-network.sh" ]; then
            bash scripts/configure-network.sh
        else
            log_warn "네트워크 설정 스크립트를 찾을 수 없습니다."
            log_info "수동 설정은 docs/DEPLOYMENT_GUIDE.md를 참조하세요."
        fi
    else
        log_info "네트워크 설정을 건너뜁니다."
        echo ""
        echo -e "${YELLOW}나중에 설정하려면:${NC}"
        echo "  ./scripts/configure-network.sh"
        echo ""
    fi
}

# 설치 완료 메시지
print_completion() {
    domain=$(grep "^DOMAIN=" .env | cut -d'=' -f2)
    host_bind=$(grep "^HOST_BIND=" .env | cut -d'=' -f2)
    web_port=$(grep "^AERIAL_WEB_PORT=" .env | cut -d'=' -f2)
    domain=${domain:-localhost}
    host_bind=${host_bind:-0.0.0.0}
    web_port=${web_port:-18100}

    echo ""
    echo -e "${GREEN}=============================================="
    echo "         설치가 완료되었습니다!"
    echo "==============================================${NC}"
    echo ""
    echo -e "${BLUE}접속 정보:${NC}"
    echo "  웹 UI: http://$domain:$web_port"
    echo "  API 문서: 프로덕션 외부 비공개"
    echo "  호스트 바인드: $host_bind:$web_port"
    echo ""
    echo -e "${BLUE}관리 도구:${NC}"
    echo "  Flower debug: docker compose --profile debug up -d flower-debug"
    echo "  Flower URL: http://127.0.0.1:18055"
    echo ""
    echo -e "${YELLOW}다음 단계:${NC}"
    echo "  1. 설치 시 출력된 관리자 계정으로 웹 UI 로그인"
    echo "  2. 테스트 프로젝트 생성 및 이미지 업로드 테스트"
    echo "  3. 처리 기능 테스트"
    echo ""
    engine_license=$(grep "^ENGINE_LICENSE_KEY=" .env | cut -d'=' -f2)
    if [ -z "$engine_license" ]; then
        echo -e "${YELLOW}처리 엔진 라이선스 설정:${NC}"
        echo "  .env 파일에서 ENGINE_LICENSE_KEY를 설정한 후:"
        echo "  ./scripts/reload-env.sh worker-engine"
        echo ""
    fi

    echo -e "${BLUE}유용한 명령어:${NC}"
    echo "  서비스 상태: docker compose ps"
    echo "  로그 확인: docker compose logs -f"
    echo "  환경변수 변경 반영: ./scripts/reload-env.sh"
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
    setup_mount_dependency
    run_healthcheck
    setup_network
    print_completion
}

# 스크립트 실행
main "$@"
