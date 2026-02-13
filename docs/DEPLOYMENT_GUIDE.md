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
9. [버전 업그레이드](#버전-업그레이드)
10. [문제 해결](#문제-해결)

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
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi
```

### 3. 저장소 경로 준비

대용량 디스크에 데이터 디렉토리를 생성합니다:

```bash
# 예: /data 드라이브에 설정
sudo mkdir -p /data/aerial-survey/processing
sudo mkdir -p /data/aerial-survey/storage    # 로컬 모드 스토리지
# sudo mkdir -p /data/aerial-survey/minio   # MinIO 모드 스토리지
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
docker compose up -d
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
```

### 필수 설정 (스토리지)

```bash
# 스토리지 백엔드 선택: "local" (단일 서버) 또는 "minio" (S3 호환)
STORAGE_BACKEND=local

# 처리 데이터 경로 (1TB 이상 권장)
PROCESSING_DATA_PATH=/data/aerial-survey/processing
```

**로컬 모드** (`STORAGE_BACKEND=local`):
```bash
# 파일 저장 경로 (1TB 이상 권장)
LOCAL_STORAGE_PATH=/data/aerial-survey/storage
```

**MinIO 모드** (`STORAGE_BACKEND=minio`):
```bash
MINIO_ACCESS_KEY=your-minio-access-key
MINIO_SECRET_KEY=your-very-secure-minio-secret-key
MINIO_DATA_PATH=/data/aerial-survey/minio

# 브라우저에서 MinIO에 접근하는 주소 (presigned URL 생성용)
MINIO_PUBLIC_ENDPOINT=your-domain.com
```

> 단일 서버 환경에서는 **로컬 모드**를 권장합니다. MinIO 없이 운영 가능하며 파일 복사 오버헤드가 없습니다.

### 필수 설정 (라이선스)

```bash
# Metashape 라이선스 키
METASHAPE_LICENSE_KEY=your-metashape-license-key
```

### 선택 설정 (오프라인 타일맵)

```bash
# 오프라인 타일맵 사용 여부 (true/false)
VITE_MAP_OFFLINE=true

# 타일 URL 패턴 (확장자 없음 - nginx가 .jpg/.png 자동 감지)
VITE_TILE_URL=/tiles/{z}/{x}/{y}

# 호스트의 타일 디렉토리 경로
TILES_PATH=/path/to/tiles
```

> ℹ️ 오프라인 타일맵 상세 설정은 [ADMIN_GUIDE.md](ADMIN_GUIDE.md)의 "오프라인 타일맵 설정" 섹션을 참고하세요.

### 선택 설정 (기타)

```bash
# 도메인 (SSL 설정 시)
DOMAIN=app.example.com

# 외부 처리 엔진 (선택)
EXTERNAL_ENGINE_URL=
EXTERNAL_ENGINE_API_KEY=
```

---

## 네트워크 설정

### 고정 IP 설정 (권장)

서버의 위치를 옮기거나 네트워크 환경이 변경되어도 일관된 접근을 위해 고정 IP를 설정합니다.

#### Ubuntu Desktop (NetworkManager 사용)

```bash
# 네트워크 인터페이스 확인
ip addr show

# 현재 연결 이름 확인
nmcli connection show

# 고정 IP 설정 (예: eth0 인터페이스, 192.168.0.100)
sudo nmcli connection modify "유선 연결 1" \
  ipv4.addresses 192.168.0.100/24 \
  ipv4.gateway 192.168.0.1 \
  ipv4.dns "8.8.8.8,8.8.4.4" \
  ipv4.method manual

# 연결 재시작 (SSH 연결이 끊길 수 있음)
sudo nmcli connection down "유선 연결 1" && sudo nmcli connection up "유선 연결 1"

# 설정 확인 (valid_lft forever 확인)
ip addr show
```

#### Ubuntu Server (Netplan 사용)

```bash
# netplan 설정 파일 편집
sudo nano /etc/netplan/00-installer-config.yaml
```

```yaml
network:
  version: 2
  ethernets:
    enp0s31f6:  # 실제 인터페이스 이름으로 변경
      addresses:
        - 192.168.0.100/24
      routes:
        - to: default
          via: 192.168.0.1
      nameservers:
        addresses:
          - 8.8.8.8
          - 8.8.4.4
```

```bash
# 설정 적용
sudo netplan apply
```

### hosts 파일 설정

클라이언트(접속하는 PC)의 hosts 파일에 도메인을 추가합니다:

```bash
# Linux/Mac: /etc/hosts
# Windows: C:\Windows\System32\drivers\etc\hosts

192.168.0.100    ortho.local
```

### 방화벽 포트 설정

외부에 노출해야 하는 포트:

| 포트 | 서비스 | 노출 필요 |
|------|--------|----------|
| 80/443 | Nginx (웹) | O |
| 8081 | Nginx (HTTP) | O (SSL 미사용 시) |
| 5434 | PostgreSQL | X (내부만) |
| 6380 | Redis | X (내부만) |
| 9002-9003 | MinIO (MinIO 모드만) | X (내부만) |
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

# MinIO 상태 확인 (MinIO 모드만 해당)
curl http://localhost:9002/minio/health/live

# GPU 확인
docker compose exec worker-engine nvidia-smi
```

### 3. 기능 테스트

1. 웹 UI 접속: `https://your-domain.com`
2. 회원가입 및 로그인
3. 테스트 프로젝트 생성
4. 소규모 이미지 업로드 테스트
5. 처리 시작 및 완료 확인

---

## 버전 업그레이드

기존 버전에서 새 버전으로 업그레이드하면서 프로젝트 데이터를 유지하는 절차입니다.

### 데이터 구조 이해

업그레이드 전 데이터가 어디에 저장되는지 파악해야 합니다:

| 데이터 | 저장 위치 | 유형 | 업그레이드 시 처리 |
|--------|-----------|------|-------------------|
| DB (프로젝트, 사용자 등) | Docker named volume (`_pgdata`) | Docker 볼륨 | **COMPOSE_PROJECT_NAME 고정 시 자동 유지** |
| 업로드 이미지, 정사영상 | `LOCAL_STORAGE_PATH` 또는 `MINIO_DATA_PATH` | 호스트 디렉토리 | 경로 동일하면 자동 유지 |
| 처리 중간 파일 | `PROCESSING_DATA_PATH` 호스트 경로 | 호스트 디렉토리 | 경로 동일하면 자동 유지 |
| 오프라인 타일 | `TILES_PATH` 호스트 경로 | 호스트 디렉토리 | 경로 동일하면 자동 유지 |
| 엔진 라이선스 | Docker named volume (`_engine-license`) | Docker 볼륨 | **COMPOSE_PROJECT_NAME 고정 시 자동 유지** |

> **핵심**: `COMPOSE_PROJECT_NAME=aerial-survey-manager`가 `.env`에 설정되어 있으면, Docker named volume의 접두사가 폴더명과 무관하게 고정됩니다.
> 따라서 새 패키지 폴더에서 `.env`만 복사하면 **DB 볼륨이 자동으로 재사용**됩니다.

#### 프로젝트당 데이터 저장 위치 (2026-02-13 업데이트)

하나의 프로젝트가 생성~처리 완료되면 다음 데이터가 생성됩니다:

**로컬 모드** (`STORAGE_BACKEND=local`):
```
스토리지 (LOCAL_STORAGE_PATH)
├── images/{id}/*.tif                  <- 원본 이미지 (업로드 시)
├── projects/{id}/thumbnails/*.jpg     <- 썸네일 (자동 생성)
└── projects/{id}/ortho/result_cog.tif <- 정사영상 COG (처리 완료 시)
```

**MinIO 모드** (`STORAGE_BACKEND=minio`):
```
MinIO (MINIO_DATA_PATH)
├── projects/{id}/uploads/*.tif        <- 원본 이미지 (업로드 시)
├── projects/{id}/thumbnails/*.jpg     <- 썸네일 (자동 생성)
└── projects/{id}/ortho/result_cog.tif <- 정사영상 COG (처리 완료 시)
```

**공통**:
```
처리 데이터 (PROCESSING_DATA_PATH)
└── processing/{id}/
    ├── .work/status.json              <- 처리 상태 (진행률, GSD)
    └── .work/.processing.log          <- 처리 로그

DB (Docker volume)
├── projects 테이블                    <- 프로젝트 메타데이터, bounds, area, region
├── processing_jobs 테이블             <- 처리 이력, GSD, checksum
└── images 테이블                      <- 이미지 목록, 업로드 상태
```

### 업그레이드 방식 선택

| 조건 | 방식 | DB 처리 |
|------|------|---------|
| `.env`에 `COMPOSE_PROJECT_NAME=aerial-survey-manager` 있음 | **간편 업그레이드** | 자동 유지 (alembic 자동 마이그레이션) |
| `.env`에 `COMPOSE_PROJECT_NAME` 없음 (최초 업그레이드) | **표준 업그레이드** | pg_dump/restore 필요 |

---

### 간편 업그레이드 (권장)

`.env`에 `COMPOSE_PROJECT_NAME=aerial-survey-manager`가 이미 설정된 경우의 절차입니다.
DB 볼륨이 폴더명과 무관하게 유지되므로 pg_dump/restore가 필요 없습니다.

#### Step 1. 기존 서비스 중지

```bash
cd ~/aerial-survey-manager    # 또는 기존 배포 폴더

# .env 백업 (필수!)
cp .env ~/env_backup

# 서비스 중지 (볼륨은 유지)
docker compose down
```

> **주의**: `docker compose down -v`가 아닌 `docker compose down`을 사용합니다.
> `-v` 플래그는 DB 볼륨을 삭제하므로 간편 업그레이드에서는 사용하지 않습니다.

#### Step 2. 새 배포 패키지 설치

```bash
cd ~

# 새 패키지 압축 해제
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0

# 기존 .env 복사
cp ~/env_backup .env

# Docker 이미지 로드
./load-images.sh
```

> **주의**: `install.sh`는 실행하지 않습니다. `install.sh`는 초기 설치 전용으로, 비밀번호를 랜덤 재생성하기 때문에 업그레이드 시 실행하면 MinIO/DB 접근이 깨집니다.

#### Step 3. 서비스 시작

```bash
docker compose up -d
```

이 때 자동으로 수행되는 작업:
1. **DB 볼륨 재사용**: `COMPOSE_PROJECT_NAME`이 동일하므로 기존 `aerial-survey-manager_pgdata` 볼륨 사용
2. **Alembic 마이그레이션**: `entrypoint.sh`가 `alembic upgrade head`를 실행하여 새 컬럼/테이블 자동 추가
3. **시드 데이터 확인**: 카메라 모델, 권역 데이터가 이미 존재하면 스킵

#### Step 4. 결과 확인

```bash
# 1. 서비스 상태 확인
docker compose ps

# 2. API 로그에서 마이그레이션 확인
docker compose logs api | grep -i "migration"

# 3. 기존 프로젝트 수 확인
docker compose exec db psql -U postgres -d aerial_survey \
  -c "SELECT count(*) FROM projects"

# 4. 웹 UI에서 기존 프로젝트 목록 및 정사영상 표시 확인
```

#### Step 5. 이전 버전 이미지 정리 (선택)

이전 버전의 Docker 이미지가 디스크에 남아 공간을 차지합니다 (이미지당 수 GB).
업그레이드 확인 후 정리를 권장합니다.

```bash
# 사용하지 않는 이미지 정리 (현재 실행 중인 이미지는 보호됨)
docker image prune -a -f
```

#### Step 6. 기존 프로젝트 스토리지 정리 (선택)

이전 버전에서 처리된 프로젝트에는 중복 파일이 남아있을 수 있습니다.
정리 스크립트로 불필요한 파일을 삭제하여 저장소를 확보할 수 있습니다.

```bash
# 미리보기 (삭제하지 않음, 절약 가능한 용량만 확인)
./scripts/cleanup-storage.sh

# 실제 삭제
./scripts/cleanup-storage.sh --execute
```

정리 대상:

| 파일 | 위치 | 삭제 조건 | 설명 |
|------|------|-----------|------|
| `result.tif` | MinIO `projects/{id}/ortho/` | 같은 프로젝트에 `result_cog.tif`가 있을 때 | COG 변환 전 원본 (불필요) |
| `result_cog.tif` | 로컬 `processing/{id}/output/` | MinIO에 `result_cog.tif`가 있을 때 | 로컬 복사본 (MinIO가 primary) |

> 프로젝트 자체는 삭제하지 않습니다. 중복 **파일만** 정리합니다.
> 기본 모드는 dry-run이므로 안전하게 미리보기할 수 있습니다.

---

### 표준 업그레이드 (최초 업그레이드)

`.env`에 `COMPOSE_PROJECT_NAME`이 없는 경우의 절차입니다.
Docker 볼륨 접두사가 폴더명에 의존하므로 DB를 백업/복원해야 합니다.

#### Step 1. 기존 환경에서 백업

```bash
# 기존 배포 폴더로 이동
cd ~/aerial-survey-manager-v1.0.5

# DB 백업
docker compose exec db pg_dump -U postgres aerial_survey > ~/backup.sql

# .env 백업
cp .env ~/env_backup
```

#### Step 2. 기존 서비스 중지 및 볼륨 삭제

```bash
# 서비스 중지 + Docker 볼륨 삭제
# (DB는 backup.sql로 백업했으므로 볼륨 삭제해도 안전)
docker compose down -v
```

> `-v` 플래그가 `_pgdata`, `_redis_data`, `_engine-license` 볼륨을 삭제합니다.
> 호스트 디렉토리(MinIO, 처리 데이터, 타일)는 영향받지 않습니다.

#### Step 3. 새 배포 패키지 설치

```bash
# 새 패키지 압축 해제
cd ~
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0

# 기존 .env 복사
cp ~/env_backup .env

# COMPOSE_PROJECT_NAME 추가 (이후 업그레이드부터 간편 업그레이드 가능)
echo '' >> .env
echo 'COMPOSE_PROJECT_NAME=aerial-survey-manager' >> .env

# install.sh 실행 (기존 .env 유지 선택)
./scripts/install.sh
```

> `install.sh`가 `.env` 파일을 감지하면 덮어쓸지 묻습니다. **기존 유지**를 선택하세요.

#### Step 4. DB 복원

```bash
# DB 사용 서비스 중지
docker compose stop api celery-worker celery-beat

# install.sh가 만든 빈 DB 삭제 → 재생성
docker compose exec db dropdb -U postgres aerial_survey
docker compose exec db createdb -U postgres aerial_survey

# 백업 데이터 복원
docker compose exec -T db psql -U postgres aerial_survey < ~/backup.sql

# 서비스 재시작 (API 시작 시 alembic이 새 컬럼 자동 추가)
docker compose start api celery-worker celery-beat
```

#### Step 5. 결과 확인

```bash
# 1. 서비스 상태 확인
docker compose ps

# 2. API 헬스체크
curl http://localhost:8081/health

# 3. DB 연결 및 데이터 확인
docker compose exec db psql -U postgres -d aerial_survey \
  -c "SELECT count(*) FROM projects"

# 4. 웹 UI 접속하여 기존 프로젝트 목록 확인

# 5. 기존 프로젝트의 정사영상 표시 확인
```

#### Step 6. 기존 프로젝트 스토리지 정리 (선택)

간편 업그레이드의 Step 6과 동일합니다. `./scripts/cleanup-storage.sh`를 실행하세요.

---

### 확인 체크리스트

- [ ] 모든 서비스가 `Up` 상태인가? (`docker compose ps`)
- [ ] API 로그에 "Migrations applied successfully" 표시되는가?
- [ ] 기존 프로젝트 목록이 보이는가?
- [ ] 기존 프로젝트의 썸네일/정사영상이 표시되는가?
- [ ] 새 프로젝트 생성이 가능한가?
- [ ] 오프라인 타일맵이 정상 표시되는가? (해당 시)
- [ ] 기존 프로젝트의 정사영상 다운로드가 가능한가?

### 주의사항

- **`.env` 백업은 필수**: `install.sh`는 비밀번호를 랜덤 생성하므로, 기존 `.env`를 잃으면 데이터에 접근할 수 없습니다
- **MinIO 인증 정보 일치** (MinIO 모드): `.env`의 `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`가 기존과 동일해야 합니다
- **호스트 경로 일치**: `LOCAL_STORAGE_PATH`(또는 `MINIO_DATA_PATH`), `PROCESSING_DATA_PATH`, `TILES_PATH`가 기존과 동일해야 합니다
- **스토리지 백엔드 변경 주의**: `STORAGE_BACKEND`를 변경하면 기존 파일에 접근할 수 없습니다. 마이그레이션이 필요합니다
- **엔진 라이선스**: 간편 업그레이드 시 라이선스 볼륨이 유지됩니다. 표준 업그레이드(`down -v`) 시에는 볼륨이 삭제되므로 재활성화가 필요합니다. 라이선스 볼륨이 유지된 경우, 다음 처리 시 로컬 검증만 수행하며 서버에 재활성화 요청을 보내지 않습니다

### DB 스키마 자동 마이그레이션

API 컨테이너가 시작되면 `entrypoint.sh`에서 `alembic upgrade head`가 자동 실행됩니다.
이를 통해 새 버전에서 추가된 DB 컬럼/테이블이 기존 DB에 자동으로 반영됩니다.

```
API 시작 → DB 연결 대기 → alembic upgrade head → 시드 데이터 확인 → 서버 시작
```

- 이미 최신 상태인 DB에서는 "No upgrade needed" 메시지 출력
- 새 컬럼 추가 시 기존 데이터에 기본값이 자동 설정됨 (예: `source_deleted = false`)
- pg_dump/restore로 복원된 DB에도 `alembic_version` 테이블이 포함되어 있으므로 누락된 마이그레이션만 적용됨

### 호환성 보장

새 버전의 코드는 기존 프로젝트 데이터와 **하위 호환**됩니다:

| 기존 상태 | 새 버전에서의 동작 |
|-----------|-------------------|
| 로컬에 `output/result_cog.tif` 있음 | 그대로 사용 (다운로드 시 로컬 우선) |
| MinIO에 `result.tif`만 있음 | 다운로드 시 MinIO에서 서빙 (COG 폴백) |
| MinIO에 `result_cog.tif` 있음 | TiTiler 타일 서빙 정상 동작 |
| `source_deleted` 컬럼 없음 | alembic이 자동 추가 (`false` 기본값) |

> 기존 프로젝트는 **아무런 수정 없이** 새 버전에서 정상 동작합니다.
> `cleanup-storage.sh`는 선택사항이며, 저장소 절약이 필요할 때만 실행하면 됩니다.

---

## 문제 해결

### GPU가 인식되지 않음

```bash
# NVIDIA 드라이버 확인
nvidia-smi

# Docker에서 GPU 접근 확인
docker run --rm --gpus all nvidia/cuda:12.0.0-base-ubuntu22.04 nvidia-smi

# Container Toolkit 재설치
sudo apt-get install --reinstall nvidia-container-toolkit
sudo systemctl restart docker
```

### MinIO 업로드 실패 (507 Storage Full) — MinIO 모드만 해당

```bash
# 디스크 용량 확인
df -h /data/aerial-survey/minio

# 임시 파일 정리
docker compose exec minio mc rm --recursive --force /data/.minio.sys/tmp/
```

### 처리 실패 시 외부 COG 삽입

Metashape 처리가 반복 실패하는 경우, 외부에서 생성한 정사영상(GeoTIFF/COG)을 삽입하여 프로젝트를 완료 상태로 만들 수 있습니다:

```bash
# 기본 사용
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif

# GSD 수동 지정 + 처리 중 작업 강제 취소
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --gsd 5.0 --force
```

> 상세 사용법은 [ADMIN_GUIDE.md](ADMIN_GUIDE.md)의 "외부 COG 삽입" 섹션을 참고하세요.

### Metashape 라이선스 오류

처리 시작 시 라이선스가 이미 활성화된 상태이면 서버 호출 없이 로컬 검증만 수행합니다.
라이선스 오류가 지속될 경우:

```bash
# 라이선스 볼륨 초기화
docker volume rm aerial-survey-manager_metashape-license
docker compose up -d worker-engine

# 로그 확인
docker compose logs worker-engine | grep -i license
```

> 상세 내용은 [ADMIN_GUIDE.md](ADMIN_GUIDE.md)의 "Metashape Licensing Management" 섹션을 참고하세요.

### 데이터베이스 연결 실패

```bash
# DB 컨테이너 상태 확인
docker compose logs db

# 수동 연결 테스트
docker compose exec db psql -U postgres -d aerial_survey -c "SELECT 1"
```

### 오프라인 타일맵이 표시되지 않음

```bash
# nginx 컨테이너 내부에서 타일 경로 확인
docker compose exec nginx ls /data/tiles/

# "No such file or directory" 출력 시: bind mount 문제
# 원인: 타일 폴더를 삭제 후 재생성하면 Docker bind mount가 끊어짐
# 해결: nginx 재시작
docker compose restart nginx

# 타일 경로가 정상인데도 회색 배경인 경우: 브라우저 캐시 삭제
# Ctrl+Shift+R (하드 리프레시) 또는 시크릿 모드에서 확인
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
