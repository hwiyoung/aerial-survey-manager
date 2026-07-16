# 배포 가이드

배포 패키지 설치 및 업그레이드 절차입니다.

---

## 시스템 요구사항

| 항목 | 최소 | 권장 |
|------|------|------|
| CPU | 8코어 | 16코어 |
| RAM | 32GB | 64GB |
| GPU | NVIDIA CUDA | RTX 3080+ |
| 저장소 | 1TB SSD | 4TB+ NVMe |
| OS | Ubuntu 20.04/22.04 LTS | |
| Docker | 24.0+ | |
| NVIDIA Driver | 525+ | |
| NVIDIA Container Toolkit | 최신 | |

> Docker 설치: https://docs.docker.com/engine/install/ubuntu/
> NVIDIA Container Toolkit: https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html

**필수 사전 설치 (순서대로):**
1. NVIDIA 드라이버 (`nvidia-smi`로 확인)
2. NVIDIA Container Toolkit (`nvidia-ctk --version`으로 확인)
3. Docker runtime에 nvidia 등록 (`docker info | grep -i nvidia`로 확인)

> Container Toolkit이 없으면 GPU가 컨테이너에 전달되지 않아 처리 속도가 10배 이상 느려집니다. 시스템은 오류 없이 CPU 모드로 동작하므로 반드시 사전에 확인하세요.

---

## 신규 설치

### 1. 패키지 설치
```bash
tar -xzf aerial-survey-manager.tar.gz
cd aerial-survey-manager
./load-images.sh
./scripts/install.sh
```

### 2. 필수 환경변수 (.env)

| 변수 | 설명 | 예시 |
|------|------|------|
| `POSTGRES_PASSWORD` | DB 비밀번호 | `openssl rand -hex 16` |
| `JWT_SECRET_KEY` | JWT 서명 키 (32자+) | `openssl rand -hex 32` |
| `ALLOW_WEAK_JWT_SECRET` | 약한 JWT 키 허용 여부 | 배포는 반드시 `false` |
| `STORAGE_BACKEND` | `local` 또는 `minio` | `local` |
| `AERIAL_CONTAINER_UID/GID` | API·일반 Celery 파일 소유자 | 설치 스크립트가 자동 설정 |
| `AERIAL_DATA_ROOT` | 신규 설치용 데이터 기준 경로 | `./data` |
| `LOCAL_STORAGE_PATH` | 로컬 스토리지 기준 경로 | `./data` |
| `PROCESSING_DATA_PATH` | 프로젝트별 소스/처리 데이터 경로 | `./data/projects` |
| `EXPORT_ROOT_PATH` | 최종 COG 정사영상 경로 | `./data/orthomosaic` |
| `AUTO_EXPORT_ENABLED` | 별도 자동 내보내기 활성화 | `false` |
| `AUTO_EXPORT_TARGET_CRS` | 최종 COG 목표 좌표계 | `EPSG:5186` |
| `ENGINE_LICENSE_KEY` | 처리 엔진 라이선스 키 | |

**오프라인 타일맵 (선택):**

| 변수 | 설명 |
|------|------|
| `VITE_MAP_OFFLINE` | `true` |
| `VITE_TILE_URL` | `/tiles/{z}/{x}/{y}` |
| `TILES_PATH` | 호스트 타일 디렉토리 경로 |

> 신규 배포 패키지는 설치 폴더 기준 상대경로인 `./data`를 사용합니다. 외장 디스크를 사용할 때만 절대경로로 바꾸세요. 컨테이너에는 `LOCAL_STORAGE_PATH/projects`만 `/data/storage/projects`로, `EXPORT_ROOT_PATH`가 `/data/storage/orthomosaic`와 `/data/exports`로 마운트되므로 `LOCAL_STORAGE_PATH/orthomosaic` 더미 디렉토리는 만들 필요가 없습니다. 기존 설치는 `LOCAL_STORAGE_PATH`, `PROCESSING_DATA_PATH`, `EXPORT_ROOT_PATH`, `TILES_PATH`, `MINIO_DATA_PATH` 값을 그대로 유지해도 됩니다.
> 전체 변수 목록: `.env.example` 참조

### 3. GPU 연결 확인
```bash
# 컨테이너에서 GPU 인식 확인 (필수)
docker compose exec worker-engine nvidia-smi
```
실패 시 → [문제 해결 > GPU 미인식](#문제-해결) 참조

### 4. 서비스 시작 및 확인
```bash
docker compose up -d
docker compose ps              # 모든 서비스 Up 확인
curl http://127.0.0.1:18100/health   # API 응답 확인
```

### 5. 접속
- 기본 웹 UI: `http://배포PC_IP:18100`
- 배포PC에서만 접속하게 제한하려면 `.env`의 `HOST_BIND`를 `127.0.0.1`로 변경
- 최초 조직 공동 운영 계정: `.env`의 `ADMIN_EMAIL` / `ADMIN_PASSWORD`
- `ADMIN_*` 이름은 기존 배포 패키지 호환용이며 관리자·일반 사용자 역할을 구분하지 않습니다.
- 신규 DB에서 두 값이 없거나 비밀번호가 12자 미만이면 API가 시작되지 않습니다.
- 설치 중 비밀번호 입력을 생략하면 임의 비밀번호가 한 번 출력됩니다.
- 기존 계정이 있는 업그레이드 설치에서는 기존 계정과 비밀번호가 그대로 유지됩니다.

---

## 버전 업그레이드

### 간편 업그레이드 (.env에 `COMPOSE_PROJECT_NAME=aerial_survey_manager`가 있는 경우)

```bash
# 1. 백업
cp .env ~/env_backup

# 2. 서비스 중지 (볼륨 유지 — -v 금지!)
docker compose down

# 3. 새 패키지 설치
cd ~
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0
cp ~/env_backup .env
./load-images.sh

# 4. 시작 (DB 마이그레이션 자동 실행)
docker compose up -d

# 5. 확인
docker compose ps
docker compose exec db psql -U postgres -d aerial_survey -c "SELECT count(*) FROM projects"
```

> `install.sh`를 실행하지 마세요. 비밀번호가 재생성되어 기존 데이터에 접근할 수 없게 됩니다.

### 표준 업그레이드 (`COMPOSE_PROJECT_NAME`이 없는 최초 업그레이드)

```bash
# 1. 기존 환경에서 백업
docker compose exec db pg_dump -U postgres aerial_survey > ~/backup.sql
cp .env ~/env_backup

# 2. 기존 중지 + 볼륨 삭제
docker compose down -v

# 3. 새 패키지 설치
cd ~
tar -xzf aerial-survey-manager-v1.1.0.tar.gz
cd aerial-survey-manager-v1.1.0
cp ~/env_backup .env
echo 'COMPOSE_PROJECT_NAME=aerial_survey_manager' >> .env

# 4. DB 복원
docker compose up -d db
sleep 5
docker compose exec db dropdb -U postgres aerial_survey
docker compose exec db createdb -U postgres aerial_survey
docker compose exec -T db psql -U postgres aerial_survey < ~/backup.sql

# 5. 전체 시작
docker compose up -d
```

### 업그레이드 확인 체크리스트

- [ ] `docker compose ps` — 모든 서비스 Up
- [ ] 기존 프로젝트 목록이 보이는가
- [ ] 기존 정사영상이 지도에 표시되는가
- [ ] 새 프로젝트 생성이 가능한가

---

## 보안 설정 (선택)

서비스가 정상 기동된 것을 확인한 뒤 실행하세요.

```bash
docker compose ps
curl http://127.0.0.1:18100/health
sudo bash scripts/secure-deployment.sh
```

`secure-deployment.sh`는 현재 배포 폴더를 고정 symlink로 연결하고 systemd 유닛이 이 경로만 보게 합니다.

```text
/home/dell/aerial-survey-manager-current -> /home/dell/aerial-survey-manager-<version>
```

새 버전 폴더로 업그레이드한 뒤에는 새 폴더에서 반드시 다시 실행하세요.

```bash
cd /home/dell/aerial-survey-manager-<new-version>
sudo bash scripts/secure-deployment.sh
systemctl cat aerial-survey.service | grep -E 'WorkingDirectory|EnvironmentFile|ExecStart'
```

`WorkingDirectory`, `EnvironmentFile`, `ExecStart`가 고정 symlink 경로를 가리켜야 합니다. `.env`는 보안 설정 후 root-only(`600`)가 되므로 일반 사용자의 직접 `docker compose` 실행은 permission denied가 날 수 있습니다. 운영자는 `aerial-status`, `aerial-restart`, `aerial-logs`를 사용하세요.

코드 정비를 계속하는 체크아웃에서 `.env` 권한은 유지하고 자동 시작 및 GPU watchdog 경로만 갱신하려면 다음 옵션을 사용합니다.

```bash
sudo bash scripts/secure-deployment.sh --systemd-only
```

### systemd 시작 모델

`aerial-survey.service`는 핵심 서비스를 먼저 시작하고 `worker-engine`은 best-effort로 분리합니다.

- 핵심 서비스: `db`, `redis`, `api`, `frontend`, `nginx`, `celery-worker`, `celery-worker-thumbnail`, `flower`, `titiler`
- GPU 처리 엔진: `worker-engine`

GPU 드라이버나 NVIDIA Docker runtime이 부팅 직후 늦게 준비되면 `worker-engine`만 실패할 수 있습니다. 이 경우에도 핵심 서비스가 올라오면 `aerial-survey.service`는 success가 될 수 있고, `aerial-gpu-watchdog.timer`가 나중에 `worker-engine` 복구를 시도합니다.

### CORS 제한
```nginx
# nginx.conf — 프로덕션에서는 특정 도메인만 허용
add_header 'Access-Control-Allow-Origin' 'https://app.example.com' always;
```

### 관리 포트
```bash
# 운영 기본값에서는 Flower host port를 열지 않습니다.
# 필요할 때만 debug profile로 로컬 포트를 엽니다.
docker compose --profile debug up -d flower-debug
curl http://127.0.0.1:18055
```

### SSL/HTTPS
```bash
# Let's Encrypt
sudo certbot certonly --standalone -d app.example.com
cp /etc/letsencrypt/live/app.example.com/fullchain.pem ./ssl/cert.pem
cp /etc/letsencrypt/live/app.example.com/privkey.pem ./ssl/key.pem
```

### 방화벽
```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
sudo ufw deny 18132/tcp   # 개발 DB
sudo ufw deny 18179/tcp   # 개발 Redis
sudo ufw enable
```

---

## 별도 드라이브 사용 시 부팅 순서 설정

`AERIAL_DATA_ROOT`, `LOCAL_STORAGE_PATH`, `PROCESSING_DATA_PATH`, `EXPORT_ROOT_PATH`, `TILES_PATH`, `MINIO_DATA_PATH` 중 하나라도 별도 드라이브(SSD, NAS 등)에 있는 경우, **시스템 재부팅 시 드라이브가 마운트되기 전에 Docker가 먼저 시작**될 수 있습니다. 이 경우 Docker가 빈 디렉토리를 자동 생성하여 기존 데이터가 보이지 않게 됩니다.

### 증상
- 재부팅 후 정사영상이 지도에 표시되지 않음
- 내보내기 시 "정사영상을 찾을 수 없습니다" 에러
- `docker exec aerial-survey-manager-api-1 ls /data/storage/projects/` 또는 `/data/storage/orthomosaic/` 결과가 비어있음
- `LOCAL_STORAGE_PATH`와 `EXPORT_ROOT_PATH`를 별도 경로로 분리했는데, 둘 중 하나의 실제 드라이브만 마운트되어 있음

### 해결: Docker가 드라이브 마운트 이후에 시작되도록 설정

```bash
# 1. 데이터 드라이브의 마운트 포인트 확인
df -h /data    # 또는 LOCAL_STORAGE_PATH의 상위 경로

# 2. Docker 서비스에 마운트 의존성 추가
sudo systemctl edit docker.service

# 아래 내용 입력 후 저장:
[Unit]
RequiresMountsFor=/data
# ↑ AERIAL_DATA_ROOT 또는 실제 데이터 경로들의 마운트 포인트로 변경
# 예: /mnt/storage, /media/data 등

# 3. systemd 반영
sudo systemctl daemon-reload

# 4. 확인 (재부팅 후)
sudo reboot
docker exec aerial-survey-manager-api-1 ls /data/storage/projects/
```

> `RequiresMountsFor`는 systemd 표준 기능으로, 지정한 경로가 마운트될 때까지 Docker 시작을 지연시킵니다. 드라이브가 고장 등으로 마운트되지 않으면 Docker가 시작되지 않으므로, 빈 디렉토리에서 잘못 동작하는 것보다 문제를 즉시 인지할 수 있습니다.

> **참고**: `install.sh`는 별도 드라이브를 자동 감지하여 이 설정을 적용합니다. 이미 설치된 환경에서는 위 절차를 수동으로 실행하세요.

---

## 문제 해결

| 증상 | 원인 | 해결 |
|------|------|------|
| GPU 미인식 | NVIDIA 드라이버/Container Toolkit | 아래 GPU 진단 절차 참조 |
| 처리가 극도로 느림 | GPU 미사용 (CPU only) | 아래 GPU 진단 절차 참조 |
| 처리 실패 | 라이선스/이미지 문제 | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) 참조 |
| 재부팅 후 데이터 안 보임 | 드라이브 마운트 순서 | 위 [별도 드라이브 사용 시 부팅 순서 설정](#별도-드라이브-사용-시-부팅-순서-설정) 참조 |
| 내보내기 실패 | 정사영상 경로 불일치 | [ADMIN_GUIDE.md](ADMIN_GUIDE.md) 참조 |
| MinIO 507 | 디스크 부족 | `df -h`, 임시 파일 정리 |
| 타일맵 안 보임 | bind mount 끊김 | `docker compose restart nginx` |
| DB 연결 실패 | 컨테이너 미시작 | `docker compose logs db` |

### GPU 미인식 진단

컨테이너에서 GPU가 인식되지 않으면 처리 엔진이 CPU only로 동작합니다. 오류 없이 정상 시작되므로 알아차리기 어렵지만, **처리 속도가 10배 이상 느려집니다.**

```bash
# 0단계: 전체 GPU/커널/Docker runtime 진단
./scripts/check-gpu-stack.sh

# 1단계: 컨테이너 GPU 확인
docker compose exec worker-engine nvidia-smi
# → 성공하면 GPU 정상. 아래 단계 불필요.
# → "Failed to initialize NVML" 등 오류 시 계속 진행

# 2단계: 호스트 GPU 확인
nvidia-smi
# → 실패하면 현재 커널에 맞는 NVIDIA 드라이버 설치 필요:
#   ubuntu-drivers devices
#   sudo ubuntu-drivers install
#   sudo reboot

# 3단계: Container Toolkit 확인
nvidia-ctk --version
# → 없으면 설치:
#   curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
#   curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
#     sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
#     sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
#   sudo apt-get update && sudo apt-get install -y nvidia-container-toolkit

# 4단계: Docker runtime에 nvidia 등록 확인
docker info | grep -i nvidia
# → 없으면:
#   sudo nvidia-ctk runtime configure --runtime=docker
#   sudo systemctl restart docker

# 5단계: 확인
docker compose exec worker-engine nvidia-smi
```

> 또는 `scripts/fix-gpu.sh`를 사용하면 위 과정을 자동으로 수행합니다:
> `sudo bash scripts/fix-gpu.sh`
>
> 배포 설치 후 `scripts/setup-autostart.sh` 또는 `scripts/secure-deployment.sh`를 실행하면
> NVIDIA Persistence Mode와 GPU watchdog도 함께 설정됩니다.

### 커널/NVIDIA 패키지 mismatch

현재 커널과 일치하는 `linux-modules-nvidia-*$(uname -r)` 패키지가 없으면 호스트 `nvidia-smi`부터 실패할 수 있습니다. 예를 들어 커널은 `6.17.0-29`인데 NVIDIA 모듈 패키지는 `6.17.0-23`만 설치되어 있으면 `worker-engine`도 GPU를 받을 수 없습니다.

진단:

```bash
uname -r
dpkg-query -W -f='${binary:Package}\t${Version}\t${db:Status-Abbrev}\n' 'linux-modules-nvidia-*' | grep "$(uname -r)"
./scripts/check-gpu-stack.sh
```

운영자가 현재 정상 동작 중인 커널/NVIDIA stack을 명시적으로 고정해야 하는 경우에만 다음을 사용합니다.

```bash
./scripts/pin-gpu-stack.sh --list
sudo ./scripts/pin-gpu-stack.sh --hold
```

해제:

```bash
sudo ./scripts/pin-gpu-stack.sh --unhold
```

주의: hold는 커널과 드라이버 보안 업데이트 적용을 지연시킵니다. 기본 설치는 자동 hold를 수행하지 않습니다.

> 상세 운영 문제는 [ADMIN_GUIDE.md](ADMIN_GUIDE.md) 참조

---

## 백업

```bash
# DB 백업
docker compose exec db pg_dump -U postgres aerial_survey > backup_$(date +%Y%m%d).sql

# DB 복원
docker compose exec -T db psql -U postgres aerial_survey < backup.sql
```
