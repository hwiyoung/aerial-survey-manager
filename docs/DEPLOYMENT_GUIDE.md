# 외부 기관 배포 가이드

이 문서는 Aerial Survey Manager를 외부 기관에 설치하기 위한 상세 가이드입니다.

## 목차

1. [시스템 요구사항](#시스템-요구사항)
2. [사전 준비](#사전-준비)
3. [설치 절차](#설치-절차)
4. [환경 변수 설정](#환경-변수-설정)
5. [네트워크 설정](#네트워크-설정)
6. [보안 설정](#보안-설정)
7. [SSL/HTTPS 설정](#sslhttps-설정)
8. [헬스체크 및 검증](#헬스체크-및-검증)
9. [문제 해결](#문제-해결)

---

## 시스템 요구사항

### 하드웨어

| 항목 | 최소 사양 | 권장 사양 |
|------|----------|----------|
| CPU | 8코어 | 16코어 이상 |
| RAM | 32GB | 64GB 이상 |
| GPU | NVIDIA (CUDA 지원) | RTX 3080 이상 |
| 저장소 | 1TB SSD | 4TB+ NVMe |
| 네트워크 | 100Mbps | 1Gbps |

### 소프트웨어

| 항목 | 버전 |
|------|------|
| OS | Ubuntu 20.04/22.04 LTS |
| Docker | 24.0 이상 |
| Docker Compose | 2.20 이상 |
| NVIDIA Driver | 525 이상 |
| NVIDIA Container Toolkit | 최신 |

---

## 사전 준비

### 1. Docker 설치

```bash
# Docker 설치
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER

# Docker Compose 설치 (v2)
sudo apt-get update
sudo apt-get install docker-compose-plugin

# 확인
docker --version
docker compose version
```

### 2. NVIDIA 드라이버 및 Container Toolkit 설치

```bash
# NVIDIA 드라이버 설치
sudo apt-get install -y nvidia-driver-525

# NVIDIA Container Toolkit 설치
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | \
  sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker

# 확인
nvidia-smi
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu22.04 nvidia-smi
```

### 3. 저장소 경로 준비

대용량 디스크에 데이터 디렉토리를 생성합니다:

```bash
# 예: /data 드라이브에 설정
sudo mkdir -p /data/aerial-survey/processing
sudo mkdir -p /data/aerial-survey/minio
sudo chown -R $USER:$USER /data/aerial-survey
```

---

## 설치 절차

### 1. 배포 패키지 설치

```bash
# 배포 패키지 압축 해제
tar -xzf aerial-survey-manager.tar.gz
cd aerial-survey-manager

# 또는 Git clone (소스 접근 권한이 있는 경우)
git clone https://github.com/your-org/aerial-survey-manager.git
cd aerial-survey-manager
```

### 2. 자동 설치 스크립트 실행

```bash
# 설치 스크립트 실행
./scripts/install.sh
```

또는 수동 설치:

```bash
# 환경 설정 파일 생성
cp .env.production.example .env

# 환경 변수 편집
nano .env

# 서비스 시작
docker compose -f docker-compose.prod.yml up -d
```

---

## 환경 변수 설정

`.env` 파일에서 다음 변수들을 **반드시** 설정해야 합니다:

### 필수 설정 (보안)

```bash
# 데이터베이스 비밀번호 (강력한 비밀번호 필수)
POSTGRES_PASSWORD=your-very-secure-db-password-here

# JWT 서명 키 (32자 이상, 랜덤 문자열)
# 생성 방법: openssl rand -hex 32
JWT_SECRET_KEY=your-super-secret-jwt-key-minimum-32-characters

# MinIO 접근 키
MINIO_ACCESS_KEY=your-minio-access-key
MINIO_SECRET_KEY=your-very-secure-minio-secret-key
```

### 필수 설정 (네트워크)

```bash
# 브라우저에서 접근하는 주소 (도메인 또는 IP:포트)
# 예: app.example.com 또는 192.168.1.100:8081
MINIO_PUBLIC_ENDPOINT=your-domain.com
```

### 필수 설정 (저장소)

```bash
# 처리 데이터 경로 (1TB 이상 권장)
PROCESSING_DATA_PATH=/data/aerial-survey/processing

# MinIO 저장소 경로 (1TB 이상 권장)
MINIO_DATA_PATH=/data/aerial-survey/minio
```

### 필수 설정 (라이선스)

```bash
# Metashape 라이선스 키
METASHAPE_LICENSE_KEY=your-metashape-license-key
```

### 선택 설정

```bash
# 도메인 (SSL 설정 시)
DOMAIN=app.example.com

# 외부 처리 엔진 (선택)
EXTERNAL_ENGINE_URL=
EXTERNAL_ENGINE_API_KEY=
```

---

## 네트워크 설정

### 방화벽 포트 설정

외부에 노출해야 하는 포트:

| 포트 | 서비스 | 노출 필요 |
|------|--------|----------|
| 80/443 | Nginx (웹) | O |
| 8081 | Nginx (HTTP) | O (SSL 미사용 시) |
| 5434 | PostgreSQL | X (내부만) |
| 6380 | Redis | X (내부만) |
| 9002-9003 | MinIO | X (내부만) |
| 5555 | Flower | X (관리자만) |

```bash
# UFW 예시
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 5434/tcp
sudo ufw deny 9002:9003/tcp
sudo ufw enable
```

### 도메인 설정

1. DNS A 레코드 설정: `app.example.com` → 서버 IP
2. nginx 설정에서 `server_name` 수정

---

## 보안 설정

### 1. 강력한 비밀번호 생성

```bash
# JWT Secret Key 생성
openssl rand -hex 32

# 데이터베이스 비밀번호 생성
openssl rand -base64 24

# MinIO Secret Key 생성
openssl rand -base64 32
```

### 2. CORS 제한 (프로덕션)

`nginx.conf`에서 CORS 설정을 특정 도메인으로 제한:

```nginx
# 변경 전
add_header 'Access-Control-Allow-Origin' '*' always;

# 변경 후
add_header 'Access-Control-Allow-Origin' 'https://app.example.com' always;
```

### 3. 관리 포트 접근 제한

Flower, MinIO Console 등 관리 인터페이스는 내부 네트워크만 접근 가능하도록 설정:

```bash
# docker-compose.prod.yml에서 포트 바인딩을 localhost로 제한
ports:
  - "127.0.0.1:5555:5555"  # Flower
  - "127.0.0.1:9003:9001"  # MinIO Console
```

---

## SSL/HTTPS 설정

### Let's Encrypt 사용 (권장)

```bash
# Certbot 설치
sudo apt-get install certbot

# 인증서 발급 (서비스 중지 상태에서)
sudo certbot certonly --standalone -d app.example.com

# 인증서 복사
sudo cp /etc/letsencrypt/live/app.example.com/fullchain.pem ./ssl/cert.pem
sudo cp /etc/letsencrypt/live/app.example.com/privkey.pem ./ssl/key.pem
sudo chown $USER:$USER ./ssl/*.pem
```

### 기관 인증서 사용

```bash
# 인증서 파일 복사
cp your-certificate.crt ./ssl/cert.pem
cp your-private-key.key ./ssl/key.pem
```

### nginx SSL 설정 적용

`nginx.prod.conf` 파일이 자동으로 SSL을 설정합니다.

---

## 헬스체크 및 검증

### 1. 서비스 상태 확인

```bash
# 모든 서비스 상태 확인
docker compose ps

# 헬스체크 스크립트 실행
./scripts/healthcheck.sh
```

### 2. 개별 서비스 확인

```bash
# API 헬스체크
curl http://localhost:8081/health

# 데이터베이스 연결 확인
docker compose exec db pg_isready -U postgres

# MinIO 상태 확인
curl http://localhost:9002/minio/health/live

# GPU 확인
docker compose exec worker-metashape nvidia-smi
```

### 3. 기능 테스트

1. 웹 UI 접속: `https://your-domain.com`
2. 회원가입 및 로그인
3. 테스트 프로젝트 생성
4. 소규모 이미지 업로드 테스트
5. 처리 시작 및 완료 확인

---

## 문제 해결

### GPU가 인식되지 않음

```bash
# NVIDIA 드라이버 확인
nvidia-smi

# Docker에서 GPU 접근 확인
docker run --rm --gpus all nvidia/cuda:11.8-base-ubuntu22.04 nvidia-smi

# Container Toolkit 재설치
sudo apt-get install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### MinIO 업로드 실패 (507 Storage Full)

```bash
# 디스크 용량 확인
df -h /data/aerial-survey/minio

# 임시 파일 정리
docker compose exec minio mc rm --recursive --force /data/.minio.sys/tmp/
```

### Metashape 라이선스 오류

```bash
# 라이선스 볼륨 초기화
docker volume rm aerial-survey-manager_metashape-license
docker compose up -d worker-metashape

# 로그 확인
docker compose logs worker-metashape | grep -i license
```

### 데이터베이스 연결 실패

```bash
# DB 컨테이너 상태 확인
docker compose logs db

# 수동 연결 테스트
docker compose exec db psql -U postgres -d aerial_survey -c "SELECT 1"
```

---

## 백업 및 복구

### 데이터베이스 백업

```bash
# 백업
docker compose exec db pg_dump -U postgres aerial_survey > backup_$(date +%Y%m%d).sql

# 복구
docker compose exec -T db psql -U postgres aerial_survey < backup_20240101.sql
```

### MinIO 데이터 백업

```bash
# MinIO 데이터 경로 백업
tar -czvf minio_backup_$(date +%Y%m%d).tar.gz /data/aerial-survey/minio
```

---

## 지원 및 문의

문제 발생 시:
1. 로그 수집: `./scripts/collect-logs.sh`
2. 시스템 정보 수집: `./scripts/system-info.sh`
3. 수집된 정보와 함께 지원팀에 문의
