# 운영 가이드

상황별 대응 레시피입니다. 아키텍처/내부 동작은 [TECHNICAL_MANUAL.md](TECHNICAL_MANUAL.md)를 참고하세요.

---

## 환경변수 변경

```bash
# .env 수정 후 반영 (restart로는 안 됨)
./scripts/reload-env.sh

# 특정 서비스만
./scripts/reload-env.sh api worker-engine
```

---

## 로그 확인

```bash
# 처리 워커 실시간 로그
docker compose logs -f worker-engine --tail=100

# 상세 처리 로그 (프로젝트별)
docker compose exec worker-engine cat /data/processing/{project-id}/.work/.processing.log

# 특정 컨테이너 로그 비우기
sudo truncate -s 0 $(docker inspect --format='{{.LogPath}}' aerial-survey-manager-api-1)

# Docker 전체 정리
docker system prune -f
```

**로그 용량**: 기본 서비스 30MB, 처리 워커 250MB (로테이션 자동 설정)

---

## 처리 실패 대응

### 로그로 원인 확인
```bash
docker compose logs worker-engine | tail -50
```
처리 실패 시 `.processing.log` 마지막 20줄이 자동 출력됩니다.

### "Empty DEM" 오류
처리 중단 후 재시작 시 발생 가능. EO 파일명과 이미지 파일명 일치 여부를 확인하세요:
```bash
docker compose exec worker-engine ls /data/processing/{project-id}/images/metadata.txt
```
해결: EO 재업로드 또는 프로젝트 재생성

### 외부 COG 삽입 (처리 우회)
Metashape 처리가 반복 실패할 때, 외부 정사영상을 직접 삽입:
```bash
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif

# GSD 수동 지정 (Geographic CRS인 경우)
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --gsd 5.0

# 처리 중인 작업 강제 취소 후 삽입
./scripts/inject-cog.sh <project_id> /path/to/orthomosaic.tif --force
```

---

## 라이선스 관리 (Metashape)

### 정상 동작
처리 시작 시 로컬 `.lic` 파일로 검증. 이미 활성화되어 있으면 서버 호출 없음.

### "Key Already In Use" 오류
1. Agisoft 지원팀에 라이선스 초기화(Deactivation) 요청
2. 승인 후:
```bash
docker compose up -d --force-recreate worker-engine
docker exec worker-engine python3 /app/engines/metashape/dags/metashape/activate.py
```

### 라이선스 수동 비활성화
```bash
# 개발 환경
docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.py
# 배포 환경
docker exec aerial-worker-engine python3 /app/engines/metashape/dags/metashape/deactivate.pyc
```

### 라이선스 볼륨 초기화
```bash
docker volume rm aerial-survey-manager_metashape-license
docker compose up -d worker-engine
```

> `docker-compose.yml`의 MAC 주소(`02:42:AC:17:00:64`)를 변경하면 Agisoft가 새 컴퓨터로 인식합니다. 절대 변경하지 마세요.

---

## 오프라인 타일맵

### 타일 교체 (서비스 중단 없음)
```bash
# 폴더 안의 파일만 교체 (폴더 자체를 삭제하면 안 됨)
rm -rf /path/to/tiles/*
cp -r /new/tiles/* /path/to/tiles/
```
폴더를 삭제/재생성한 경우: `docker compose restart nginx`

### 환경변수
```bash
VITE_MAP_OFFLINE=true                    # 빌드 타임 — 변경 시 프론트엔드 재빌드 필요
VITE_TILE_URL=/tiles/{z}/{x}/{y}         # 빌드 타임 — 확장자 불필요 (nginx 자동 감지)
TILES_PATH=/path/to/tiles                # 런타임 — nginx 재시작만 필요
```

### 타일 관련 문제
- **회색 화면**: `docker compose exec nginx ls /data/tiles/` → 빈 출력이면 `docker compose restart nginx`
- **이전 타일 표시**: 브라우저 Ctrl+Shift+R (하드 리프레시)

---

## 저장소 관리

### 원본 이미지 삭제
처리 완료 프로젝트의 InspectorPanel에서 삭제 버튼 클릭. 정사영상(COG)은 유지됨. 재처리 불가.

### 중복 파일 정리
```bash
# 미리보기 (삭제하지 않음)
./scripts/cleanup-storage.sh

# 실제 삭제
./scripts/cleanup-storage.sh --execute
```

### 고아 파일 정리 (DB에 없는 파일)
```bash
# 미리보기
docker compose exec api python scripts/cleanup_orphaned_data.py --minio

# 실제 삭제
docker compose exec api python scripts/cleanup_orphaned_data.py --minio --execute
```

### MinIO 용량 부족 (MinIO 모드)
```bash
# 디스크 확인
df -h $(grep MINIO_DATA_PATH .env | cut -d= -f2)

# 실패한 업로드 임시 파일 정리
docker exec aerial-survey-manager-minio-1 mc rm --recursive --force local/aerial-survey/uploads/
```

---

## 업로드 문제

### 중단된 업로드 복구
자동 복구되지 않습니다. 두 가지 방법:
1. **완료된 이미지만으로 처리**: 처리 시작 시 확인 다이얼로그에서 진행 선택
2. **수동 상태 변경 후 재업로드**:
```bash
docker exec aerial-survey-manager-db-1 psql -U postgres -d aerial_survey -c \
  "UPDATE images SET upload_status = 'interrupted' WHERE upload_status = 'uploading' AND project_id = '<project-id>';"
```

### 업로드 성능 튜닝
현재 기본값: `partSize=32MB`, `concurrency=3`, `partConcurrency=2`

| 환경 | 조정 방향 |
|------|----------|
| 느린 네트워크 | `concurrency=2`, `partConcurrency=1` |
| SSD 환경 | `partSize=64MB` 테스트 |

---

## 카메라 모델 등록

```bash
# 새 데이터만 추가
docker compose exec api python /app/scripts/seed_camera_models.py -f /app/io.csv

# 전체 초기화 후 등록
docker compose exec api python /app/scripts/seed_camera_models.py -f /app/io.csv --clear
```

---

## 큐/워커 진단

```bash
# Redis 큐 잔여량
docker compose exec redis redis-cli llen metashape
docker compose exec redis redis-cli llen thumbnail
docker compose exec redis redis-cli llen celery

# 워커 상태
docker compose ps
docker compose logs -f celery-worker --tail=50

# 정책/큐/워커 한 번에 점검
./scripts/check-processing-ops.sh
```

---

## 배포 패키지 생성 (개발 PC에서)

```bash
./scripts/build-release.sh v1.0.3
```

결과: `releases/aerial-survey-manager-v1.0.3.tar.gz`

검증:
```bash
docker run --rm aerial-prod-worker-engine:latest find /app/engines -name "*.py" -type f
# 결과 비어있어야 정상
```

---

## GPU 진단

### 증상: 처리가 극도로 느림
GPU가 컨테이너에 전달되지 않으면 Metashape가 CPU only로 동작합니다. 오류 없이 정상 시작되지만 **처리 시간이 10배 이상 증가**합니다.

### 확인
```bash
docker exec aerial-worker-engine nvidia-smi
```
`Failed to initialize NVML` 오류 시 GPU가 컨테이너에 전달되지 않고 있습니다.

### 자동 복구
```bash
sudo bash scripts/fix-gpu.sh
```

### 수동 복구 (간단한 경우)
컨테이너를 재생성(down/up)하거나 Docker 데몬을 재시작한 후 nvidia runtime 연결이 끊어진 경우:
```bash
sudo systemctl restart docker
# restart: always 설정으로 모든 컨테이너 자동 복구
docker exec aerial-worker-engine nvidia-smi   # 확인
```

위 방법으로 해결되지 않으면 NVIDIA Container Toolkit이 설치되지 않았거나 Docker runtime에 등록되지 않은 것입니다.
상세 절차는 [DEPLOYMENT_GUIDE.md](DEPLOYMENT_GUIDE.md#gpu-미인식-진단) 참조.

> GPU 복구 후 현재 진행 중인 처리는 이미 CPU 모드로 시작된 것이므로, **처리를 중단하고 다시 시작**해야 GPU를 활용합니다.

---

## 서비스 상태 점검

### 전체 헬스체크
```bash
./scripts/healthcheck.sh
```
Docker 서비스, API, DB, Redis, GPU, Celery 워커를 한 번에 점검합니다. 결과를 PASS/WARN/FAIL로 요약합니다.

### 로그 수집 (지원팀 전달용)
```bash
./scripts/collect-logs.sh
```
모든 서비스 로그, 시스템 정보, GPU 상태를 수집하여 `logs_YYYYMMDD_HHMMSS.tar.gz`로 압축합니다. 비밀번호/키는 자동 제외됩니다.

### 시스템 정보 확인
```bash
./scripts/system-info.sh
```
OS, CPU, RAM, 디스크, GPU, Docker, 네트워크 정보를 출력합니다.

---

## Metashape 안전 종료

라이선스를 비활성화한 후 종료해야 하는 경우 (서버 이전 등):
```bash
./scripts/shutdown-metashape.sh
```
1. 라이선스 비활성화
2. worker-engine 종료
3. 전체 시스템 종료 (선택)

> 일반적인 재시작/업그레이드에서는 라이선스 비활성화 불필요. 서버 교체 시에만 사용하세요.

---

## 시스템 재시작

모든 서비스에 `restart: always` 설정. 시스템 재부팅 시 자동 시작.
```bash
# Docker 자동 시작 확인/설정
sudo systemctl is-enabled docker
# 비활성 상태라면: sudo bash scripts/setup-autostart.sh

# 재부팅 후 상태 확인
docker compose ps

# GPU 전달 확인 (재부팅 후 반드시 확인)
docker exec aerial-worker-engine nvidia-smi
```

### 보안 설정 (선택)
```bash
sudo bash scripts/secure-deployment.sh
```
.env 파일 권한 제한, systemd 서비스 등록, 일반 사용자용 관리 명령어(`aerial-status`, `aerial-restart`, `aerial-logs`) 생성.

---

## 스크립트 레퍼런스

| 스크립트 | 용도 | 실행 권한 |
|----------|------|----------|
| `install.sh` | 신규 설치 (GPU 검증 포함) | 일반 |
| `build-release.sh` | 배포 패키지 생성 | 일반 |
| `reload-env.sh` | .env 변경 후 서비스 반영 | 일반 |
| `inject-cog.sh` | 외부 정사영상 COG 삽입 | 일반 |
| `cleanup-storage.sh` | 중복 파일 정리 (dry-run 기본) | 일반 |
| `check-processing-ops.sh` | 큐/워커/정책 점검 | 일반 |
| `fix-gpu.sh` | GPU 진단 및 자동 복구 | sudo |
| `healthcheck.sh` | 전체 서비스 헬스체크 | 일반 |
| `collect-logs.sh` | 로그 수집 (지원팀 전달용) | 일반 |
| `shutdown-metashape.sh` | 라이선스 비활성화 후 안전 종료 | 일반 |
| `system-info.sh` | 시스템 정보 출력 | 일반 |
| `setup-autostart.sh` | Docker 자동 시작 설정/확인 | sudo |
| `secure-deployment.sh` | 보안 설정 (권한, systemd) | sudo |
